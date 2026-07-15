import uuid
import threading
from googleapiclient.discovery import build
from .auth import get_credentials
from dateutil.parser import isoparse, ParserError
from . import local_storage


class TaskService:
    def __init__(self):
        self.creds = get_credentials()
        self.service = build('tasks', 'v1', credentials=self.creds)
        self.data = local_storage.load_data()
        self.dirty = False
        self._modified_task_ids: dict[str, set] = {}
        self._lock = threading.RLock()

        if not self.data or not self.data.get('task_lists'):
            self.sync_from_google()

        self.active_list_id = self._get_default_task_list_id()

    def _get_default_task_list_id(self):
        return self.data['task_lists'][0]['id'] if self.data.get('task_lists') else None

    def _make_temp_id(self, prefix='temp'):
        return f'{prefix}_{uuid.uuid4().hex}'

    def _mark_task_modified(self, list_id: str, task_id: str):
        if not task_id.startswith('temp_'):
            self._modified_task_ids.setdefault(list_id, set()).add(task_id)

    def sync_from_google(self):
        task_lists = self.service.tasklists().list().execute().get('items', [])
        with self._lock:
            self.data['task_lists'] = task_lists
            self.data['tasks'] = {}

        for task_list in task_lists:
            list_id = task_list['id']
            all_tasks = []
            page_token = None
            while True:
                resp = self.service.tasks().list(
                    tasklist=list_id,
                    showHidden=True,
                    maxResults=100,
                    pageToken=page_token,
                ).execute()
                all_tasks.extend(resp.get('items', []))
                page_token = resp.get('nextPageToken')
                if not page_token:
                    break
            all_tasks.sort(key=lambda t: t.get('position', ''))
            with self._lock:
                self.data['tasks'][list_id] = all_tasks

        self.save_local_data()

    def sync_to_google(self):
        if not self.dirty:
            return

        google_lists_map = {
            lst['id']: lst
            for lst in self.service.tasklists().list().execute().get('items', [])
        }

        with self._lock:
            task_lists_snapshot = list(self.data['task_lists'])

        for task_list in task_lists_snapshot:
            if task_list.get('deleted'):
                if not task_list['id'].startswith('temp_'):
                    try:
                        self.service.tasklists().delete(tasklist=task_list['id']).execute()
                    except Exception:
                        pass
            elif task_list['id'].startswith('temp_list_'):
                new_list = self.service.tasklists().insert(
                    body={'title': task_list['title']}
                ).execute()
                old_id = task_list['id']
                with self._lock:
                    for j, tl in enumerate(self.data['task_lists']):
                        if tl['id'] == old_id:
                            self.data['task_lists'][j] = new_list
                            break
                    if old_id in self.data['tasks']:
                        self.data['tasks'][new_list['id']] = self.data['tasks'].pop(old_id)
            else:
                google_list = google_lists_map.get(task_list['id'])
                if google_list and task_list.get('title') != google_list.get('title'):
                    self.service.tasklists().patch(
                        tasklist=task_list['id'],
                        body={'title': task_list['title']},
                    ).execute()

        with self._lock:
            self.data['task_lists'] = [lst for lst in self.data['task_lists'] if not lst.get('deleted')]
            valid_list_ids = {lst['id'] for lst in self.data['task_lists']}
            for lid in list(self.data['tasks'].keys()):
                if lid not in valid_list_ids:
                    del self.data['tasks'][lid]

        with self._lock:
            list_ids = list(self.data['tasks'].keys())

        for list_id in list_ids:
            if list_id.startswith('temp_list_'):
                continue

            with self._lock:
                local_tasks_snapshot = list(self.data['tasks'].get(list_id, []))

            modified_ids = self._modified_task_ids.get(list_id, set())

            new_tasks = [
                t for t in local_tasks_snapshot
                if t['id'].startswith('temp_') and not t.get('deleted')
            ]
            id_map: dict[str, str] = {}
            unprocessed = list(new_tasks)
            while unprocessed:
                processed_count = 0
                remaining = []
                for task in unprocessed:
                    old_id = task['id']
                    parent_id = task.get('parent')
                    resolved_parent = None
                    if parent_id:
                        if parent_id.startswith('temp_'):
                            resolved_parent = id_map.get(parent_id)
                            if resolved_parent is None:
                                remaining.append(task)
                                continue
                        else:
                            resolved_parent = parent_id

                    body = {
                        'title': task.get('title', ''),
                        'status': task.get('status', 'needsAction'),
                    }
                    if 'due' in task:
                        body['due'] = task['due']
                    if 'notes' in task:
                        body['notes'] = task['notes']
                    new_task = self.service.tasks().insert(
                        tasklist=list_id, body=body, parent=resolved_parent
                    ).execute()
                    id_map[old_id] = new_task['id']
                    with self._lock:
                        for t in self.data['tasks'].get(list_id, []):
                            if t['id'] == old_id:
                                t['id'] = new_task['id']
                                break
                    processed_count += 1

                if processed_count == 0 and remaining:
                    for task in remaining:
                        old_id = task['id']
                        body = {
                            'title': task.get('title', ''),
                            'status': task.get('status', 'needsAction'),
                        }
                        if 'due' in task:
                            body['due'] = task['due']
                        if 'notes' in task:
                            body['notes'] = task['notes']
                        new_task = self.service.tasks().insert(tasklist=list_id, body=body).execute()
                        with self._lock:
                            for t in self.data['tasks'].get(list_id, []):
                                if t['id'] == old_id:
                                    t['id'] = new_task['id']
                                    break
                    break
                unprocessed = remaining

            for task in local_tasks_snapshot:
                if (task['id'] in modified_ids
                        and not task['id'].startswith('temp_')
                        and not task.get('deleted')):
                    patch_body: dict = {}
                    if 'title' in task:
                        patch_body['title'] = task['title']
                    if 'notes' in task:
                        patch_body['notes'] = task.get('notes', '')
                    if 'due' in task:
                        patch_body['due'] = task['due']
                    if 'status' in task:
                        patch_body['status'] = task['status']
                    if patch_body:
                        try:
                            self.service.tasks().patch(
                                tasklist=list_id,
                                task=task['id'],
                                body=patch_body,
                            ).execute()
                        except Exception:
                            pass

            for task in local_tasks_snapshot:
                if task.get('deleted') and not task['id'].startswith('temp_'):
                    try:
                        self.service.tasks().delete(tasklist=list_id, task=task['id']).execute()
                    except Exception:
                        pass

            with self._lock:
                self.data['tasks'][list_id] = [
                    t for t in self.data['tasks'].get(list_id, [])
                    if not t.get('deleted')
                ]

        self.save_local_data()

    def save_local_data(self):
        ok = local_storage.save_data(self.data)
        if ok:
            self.dirty = False
            self._modified_task_ids.clear()
        return ok

    def get_task_lists(self):
        with self._lock:
            return [lst for lst in self.data.get('task_lists', []) if not lst.get('deleted')]

    def get_tasks_for_list(self, list_id=None):
        list_id = list_id or self.active_list_id
        if not list_id:
            return []
        with self._lock:
            return [
                task for task in self.data['tasks'].get(list_id, [])
                if not task.get('deleted') and not task.get('parent')
            ]

    def get_subtasks(self, list_id, parent_task_id):
        if not list_id or not parent_task_id:
            return []
        with self._lock:
            return [
                task for task in self.data['tasks'].get(list_id, [])
                if not task.get('deleted') and task.get('parent') == parent_task_id
            ]

    def get_task(self, list_id, task_id):
        if not list_id:
            return None
        with self._lock:
            for task in self.data['tasks'].get(list_id, []):
                if task['id'] == task_id:
                    return task
        return None

    def get_parent_task_ids(self, list_id):
        if not list_id:
            return set()
        with self._lock:
            return {t['parent'] for t in self.data['tasks'].get(list_id, []) if t.get('parent')}

    def get_children_counts(self, list_id):
        if not list_id:
            return {}
        counts: dict[str, int] = {}
        with self._lock:
            for task in self.data['tasks'].get(list_id, []):
                if task.get('parent'):
                    counts[task['parent']] = counts.get(task['parent'], 0) + 1
        return counts

    def add_task(self, list_id, title, parent=None):
        if not list_id:
            return None
        task = {
            'id': self._make_temp_id(),
            'title': title,
            'status': 'needsAction',
        }
        if parent:
            task['parent'] = parent
        with self._lock:
            self.data['tasks'].setdefault(list_id, []).append(task)
        self.dirty = True
        return task

    def add_task_body(self, list_id, task_body, index=None):
        if not list_id or not task_body:
            return None
        new_task = task_body.copy()
        new_task.pop('id', None)
        new_task.pop('deleted', None)
        new_task['id'] = self._make_temp_id()
        with self._lock:
            target = self.data['tasks'].setdefault(list_id, [])
            if index is not None:
                target.insert(index, new_task)
            else:
                target.append(new_task)
        self.dirty = True
        return new_task

    def toggle_task_status(self, list_id, task_id):
        if not list_id:
            return None
        toggled_task = None
        with self._lock:
            for task in self.data['tasks'].get(list_id, []):
                if task['id'] == task_id:
                    task['status'] = (
                        'completed' if task.get('status') == 'needsAction' else 'needsAction'
                    )
                    self.dirty = True
                    self._mark_task_modified(list_id, task_id)
                    toggled_task = task
                    break
        if not toggled_task:
            return None
        if toggled_task['status'] == 'completed':
            self._cascade_complete(list_id, task_id)
        else:
            self._cascade_uncomplete(list_id, task_id)
        return toggled_task

    def _cascade_complete(self, list_id, parent_id):
        with self._lock:
            children = [t for t in self.data['tasks'].get(list_id, []) if t.get('parent') == parent_id]
        for child in children:
            with self._lock:
                child['status'] = 'completed'
                self.dirty = True
            self._mark_task_modified(list_id, child['id'])
            self._cascade_complete(list_id, child['id'])

    def _cascade_uncomplete(self, list_id, parent_id):
        with self._lock:
            children = [t for t in self.data['tasks'].get(list_id, []) if t.get('parent') == parent_id]
        for child in children:
            with self._lock:
                child['status'] = 'needsAction'
                self.dirty = True
            self._mark_task_modified(list_id, child['id'])
            self._cascade_uncomplete(list_id, child['id'])

    def delete_task(self, list_id, task_id):
        if not list_id:
            return None
        found = False
        with self._lock:
            for task in self.data['tasks'].get(list_id, []):
                if task['id'] == task_id:
                    task['deleted'] = True
                    self.dirty = True
                    found = True
                    break
        if not found:
            return False
        with self._lock:
            child_ids = [
                t['id'] for t in self.data['tasks'].get(list_id, [])
                if t.get('parent') == task_id
            ]
        for child_id in child_ids:
            self.delete_task(list_id, child_id)
        return True

    def rename_task(self, list_id, task_id, new_name):
        if not list_id or not new_name:
            return None
        with self._lock:
            for task in self.data['tasks'].get(list_id, []):
                if task['id'] == task_id:
                    task['title'] = new_name
                    self.dirty = True
                    self._mark_task_modified(list_id, task_id)
                    return task
        return None

    def change_date_task(self, list_id, task_id, date_str):
        if not list_id:
            return None
        try:
            due_date_rfc3339 = isoparse(date_str).isoformat() + 'Z'
        except (ParserError, ValueError):
            return None
        with self._lock:
            for task in self.data['tasks'].get(list_id, []):
                if task['id'] == task_id:
                    task['due'] = due_date_rfc3339
                    self.dirty = True
                    self._mark_task_modified(list_id, task_id)
                    return task
        return None

    def change_detail_task(self, list_id, task_id, detail):
        if not list_id:
            return None
        with self._lock:
            for task in self.data['tasks'].get(list_id, []):
                if task['id'] == task_id:
                    task['notes'] = detail
                    self.dirty = True
                    self._mark_task_modified(list_id, task_id)
                    return task
        return None

    def set_active_list(self, list_id):
        self.active_list_id = list_id
        return True

    def add_list(self, list_name):
        temp_id = self._make_temp_id('temp_list')
        list_body = {'title': list_name, 'id': temp_id}
        with self._lock:
            self.data['task_lists'].append(list_body)
            self.data['tasks'][temp_id] = []
        self.dirty = True
        return list_body

    def delete_list(self, list_id):
        with self._lock:
            for i, task_list in enumerate(self.data['task_lists']):
                if task_list['id'] == list_id:
                    self.data['task_lists'][i]['deleted'] = True
                    self.dirty = True
                    return True
        return False

    def rename_list(self, list_id, new_title):
        if not list_id:
            return None
        with self._lock:
            for task_list in self.data['task_lists']:
                if task_list['id'] == list_id:
                    task_list['title'] = new_title
                    self.dirty = True
                    return True
        return None

from unicurses import *
from .task_service import TaskService
from .ui_manager import UIManager
import sys
import curses
from dateutil.parser import ParserError, isoparse
import os
import subprocess
import tempfile
import threading
import queue
from unicurses import wrapper

_sync_result_queue = queue.Queue()
_sync_thread = None


def _run_sync(service, result_queue):
    try:
        service.sync_to_google()
        result_queue.put(('ok', None))
    except Exception as exc:
        result_queue.put(('err', str(exc)))


def _trigger_background_sync(service, ui_manager):
    global _sync_thread
    if _sync_thread is not None and _sync_thread.is_alive():
        return
    ui_manager.start_sync_animation()
    _sync_thread = threading.Thread(
        target=_run_sync,
        args=(service, _sync_result_queue),
        daemon=True,
    )
    _sync_thread.start()


def open_editor_for_task_notes(stdscr, app_state, ui_manager):
    selected_task = app_state.tasks[ui_manager.selected_task_idx]
    initial_content = selected_task.get('notes', '')
    editor = os.environ.get('EDITOR', 'vim')

    with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False, mode='w+', encoding='utf-8') as tf:
        tf.write(initial_content)
        temp_path = tf.name

    def_prog_mode()
    endwin()
    subprocess.call([editor, temp_path])
    reset_prog_mode()
    doupdate()

    with open(temp_path, 'r', encoding='utf-8') as tf:
        new_note = tf.read()

    os.remove(temp_path)

    if new_note != initial_content:
        app_state.service.change_detail_task(app_state.active_list_id, selected_task['id'], new_note)
        app_state.refresh_data()


def is_valid_date(date_str):
    try:
        isoparse(date_str)
        return True
    except (ParserError, ValueError):
        return False


class AppState:
    def __init__(self, task_service):
        self.service = task_service
        self.task_lists = self.service.get_task_lists()
        self.active_list_id = self.service.active_list_id
        self.current_parent_task_id = None
        self.viewing_completed_tasks = False
        self.filtered_tasks_cache = {}
        self.task_counts = {}
        self.list_buffer = ""
        self.task_buffer = ""
        self.parent_task_id_stack = []
        self.parent_task_idx_stack = []
        self.tasks = self.get_tasks_for_active_list()
        self.tasks_due_today = self.service.get_tasks_due_today()
        self.calculate_task_counts()
        self.show_help = False

    def calculate_task_counts(self):
        for task_list in self.task_lists:
            list_id = task_list['id']
            self.task_counts[list_id] = len([
                t for t in self.service.get_tasks_for_list(list_id)
                if t.get('status') != 'completed'
            ])

    def get_tasks_for_active_list(self):
        if self.current_parent_task_id:
            all_tasks = self.service.get_subtasks(self.active_list_id, self.current_parent_task_id)
        else:
            if self.active_list_id not in self.filtered_tasks_cache or self.service.dirty:
                fetched_tasks = self.service.get_tasks_for_list(self.active_list_id)
                self.filtered_tasks_cache[self.active_list_id] = fetched_tasks
            all_tasks = self.filtered_tasks_cache[self.active_list_id]

        if self.viewing_completed_tasks:
            return [t for t in all_tasks if t.get('status') == 'completed']
        else:
            filtered = [t for t in all_tasks if t.get('status') != 'completed']
            has_completed = any(t.get('status') == 'completed' for t in all_tasks)
            if has_completed:
                filtered.append({"id": "COMPLETED_SEPARATOR", "title": "", "status": "separator", "is_button": True})
                filtered.append({"id": "SHOW_COMPLETED_BTN", "title": "--- Show Completed Tasks ---", "status": "button", "is_button": True})
            return filtered

    def refresh_data(self):
        self.task_lists = self.service.get_task_lists()
        if not self.active_list_id and self.task_lists:
            self.active_list_id = self.task_lists[0]['id']
            self.service.active_list_id = self.active_list_id
        self.filtered_tasks_cache.clear()
        self.tasks = self.get_tasks_for_active_list()
        self.tasks_due_today = self.service.get_tasks_due_today()
        self.calculate_task_counts()

    def change_active_list(self, list_id):
        if self.service.set_active_list(list_id):
            self.active_list_id = list_id
            self.current_parent_task_id = None
            self.viewing_completed_tasks = False
            self.tasks = self.get_tasks_for_active_list()
            return True
        return False


def handle_input(stdscr, app_state, ui_manager):
    try:
        key = getch()
    except curses.error:
        return True

    if key == -1:
        return True

    if key in [ord('q'), ord('Q')]:
        if _sync_thread is not None and _sync_thread.is_alive():
            ui_manager.show_temporary_message("Waiting for sync to finish...")
            _sync_thread.join(timeout=10.0)
        if app_state.service.dirty:
            ui_manager.start_sync_animation()
            app_state.service.sync_to_google()
            ui_manager.stop_sync_animation()
        return False

    if key == KEY_RESIZE:
        return True

    elif key == KEY_UP or key == ord('k'):
        if ui_manager.active_panel == 'tasks':
            ui_manager.update_task_selection(app_state.tasks, -1)
        elif ui_manager.active_panel == 'due_today':
            if ui_manager.selected_due_today_idx == 0:
                ui_manager.active_panel = 'lists'
                ui_manager.selected_list_idx = len(app_state.task_lists) - 1
            else:
                ui_manager.update_due_today_selection(app_state.tasks_due_today, -1)
        elif ui_manager.active_panel == 'lists':
            ui_manager.update_list_selection(app_state.task_lists, -1)
    elif key == KEY_DOWN or key == ord('j'):
        if ui_manager.active_panel == 'tasks':
            ui_manager.update_task_selection(app_state.tasks, 1)
        elif ui_manager.active_panel == 'lists':
            if ui_manager.selected_list_idx == len(app_state.task_lists) - 1 and app_state.tasks_due_today:
                ui_manager.active_panel = 'due_today'
                ui_manager.selected_due_today_idx = 0
            else:
                ui_manager.update_list_selection(app_state.task_lists, 1)
        elif ui_manager.active_panel == 'due_today':
            ui_manager.update_due_today_selection(app_state.tasks_due_today, 1)
    elif key == KEY_LEFT or key == ord('h'):
        if app_state.viewing_completed_tasks:
            app_state.viewing_completed_tasks = False
            app_state.refresh_data()
            ui_manager.reset_task_scroll()
        elif app_state.current_parent_task_id:
            app_state.current_parent_task_id = app_state.parent_task_id_stack.pop()
            app_state.refresh_data()
            if app_state.parent_task_idx_stack:
                ui_manager.selected_task_idx = app_state.parent_task_idx_stack.pop()
        elif ui_manager.active_panel == 'tasks':
            ui_manager.toggle_panel()
    elif key == KEY_RIGHT or key == ord('l'):
        if ui_manager.active_panel == 'due_today' and app_state.tasks_due_today:
            selected_task = app_state.tasks_due_today[ui_manager.selected_due_today_idx]
            target_list_id = selected_task.get('_list_id')
            if target_list_id:
                if app_state.active_list_id != target_list_id:
                    app_state.change_active_list(target_list_id)
                # Find the index of the task in the active list
                task_idx = 0
                for i, t in enumerate(app_state.tasks):
                    if t['id'] == selected_task['id']:
                        task_idx = i
                        break
                ui_manager.selected_task_idx = task_idx
                ui_manager.active_panel = 'tasks'
        elif ui_manager.active_panel == 'lists':
            selected_list = app_state.task_lists[ui_manager.selected_list_idx]
            if app_state.active_list_id != selected_list['id']:
                app_state.change_active_list(selected_list["id"])
                ui_manager.reset_task_scroll()
            ui_manager.toggle_panel()
        elif ui_manager.active_panel == 'tasks' and app_state.tasks:
            selected_task = app_state.tasks[ui_manager.selected_task_idx]
            if selected_task.get("is_button"):
                app_state.viewing_completed_tasks = True
                app_state.refresh_data()
                ui_manager.reset_task_scroll()
            else:
                app_state.parent_task_id_stack.append(app_state.current_parent_task_id)
                app_state.parent_task_idx_stack.append(ui_manager.selected_task_idx)
                app_state.current_parent_task_id = selected_task['id']
                app_state.refresh_data()
                ui_manager.reset_task_scroll()

    elif key == ord('c'):
        selected_task = app_state.tasks[ui_manager.selected_task_idx]
        if not selected_task.get("is_button"):
            app_state.service.toggle_task_status(app_state.active_list_id, selected_task["id"])
            app_state.refresh_data()

    elif key == ord('w'):
        _trigger_background_sync(app_state.service, ui_manager)

    elif key == ord('r'):
        if ui_manager.active_panel == 'tasks' and app_state.tasks:
            selected_task = app_state.tasks[ui_manager.selected_task_idx]
            if not selected_task.get("is_button"):
                new_title = ui_manager.get_user_input("New Task Title: ")
                app_state.service.rename_task(app_state.active_list_id, selected_task["id"], new_title)
                app_state.refresh_data()
        elif ui_manager.active_panel == 'lists' and app_state.task_lists:
            new_title = ui_manager.get_user_input("New List Title: ")
            if new_title:
                selected_list = app_state.task_lists[ui_manager.selected_list_idx]
                app_state.service.rename_list(selected_list['id'], new_title)
                app_state.refresh_data()

    elif key == ord('a'):
        if ui_manager.active_panel == 'tasks' and app_state.tasks:
            selected_task = app_state.tasks[ui_manager.selected_task_idx]
            if not selected_task.get("is_button"):
                new_date = ui_manager.get_user_input("Due Date: ", example="2026-12-25 14:30")
                if is_valid_date(new_date):
                    app_state.service.change_date_task(app_state.active_list_id, selected_task['id'], new_date)
                    app_state.refresh_data()
                else:
                    ui_manager.show_temporary_message(f"Invalid date format: '{new_date}'")

    elif key == ord('i'):
        if ui_manager.active_panel == 'tasks' and app_state.tasks:
            selected_task = app_state.tasks[ui_manager.selected_task_idx]
            if not selected_task.get("is_button"):
                open_editor_for_task_notes(stdscr, app_state, ui_manager)

    elif key == ord('K'):
        if ui_manager.active_panel == 'tasks' and app_state.tasks and ui_manager.selected_task_idx > 0:
            task = app_state.tasks[ui_manager.selected_task_idx]
            if not task.get('is_button'):
                if ui_manager.selected_task_idx == 1:
                    prev_id = None
                else:
                    prev_id = app_state.tasks[ui_manager.selected_task_idx - 2]['id']
                app_state.service.move_task(app_state.active_list_id, task['id'], previous_id=prev_id, parent_id=task.get('parent'))
                app_state.refresh_data()
                ui_manager.selected_task_idx -= 1

    elif key == ord('J'):
        if ui_manager.active_panel == 'tasks' and app_state.tasks and ui_manager.selected_task_idx < len(app_state.tasks) - 1:
            task = app_state.tasks[ui_manager.selected_task_idx]
            if not task.get('is_button'):
                next_task = app_state.tasks[ui_manager.selected_task_idx + 1]
                if not next_task.get('is_button'):
                    app_state.service.move_task(app_state.active_list_id, task['id'], previous_id=next_task['id'], parent_id=task.get('parent'))
                    app_state.refresh_data()
                    ui_manager.selected_task_idx += 1

    elif key == ord('X'):
        if ui_manager.active_panel == 'tasks':
            confirm = ui_manager.get_confirm_keypress("Clear all completed tasks?")
            if confirm.lower() == 'y':
                app_state.service.clear_completed_tasks(app_state.active_list_id)
                app_state.refresh_data()
                ui_manager.selected_task_idx = 0

    elif key == ord('d'):
        if ui_manager.active_panel == 'tasks' and app_state.tasks:
            selected_task = app_state.tasks[ui_manager.selected_task_idx]
            if not selected_task.get("is_button"):
                confirm = ui_manager.get_confirm_keypress(f"Delete '{selected_task['title'][:30]}'?")
                if confirm.lower() == 'y':
                    app_state.task_buffer = app_state.service.get_task(app_state.active_list_id, selected_task['id'])
                    app_state.service.delete_task(app_state.active_list_id, selected_task["id"])
                    app_state.refresh_data()
                    if ui_manager.selected_task_idx >= len(app_state.tasks) and len(app_state.tasks) > 0:
                        ui_manager.selected_task_idx = len(app_state.tasks) - 1
        elif ui_manager.active_panel == 'lists' and app_state.task_lists:
            selected_list = app_state.task_lists[ui_manager.selected_list_idx]
            confirm = ui_manager.get_confirm_keypress(f"Delete list '{selected_list['title']}'?")
            if confirm.lower() == 'y':
                app_state.list_buffer = selected_list['title']
                app_state.service.delete_list(selected_list["id"])
                app_state.task_lists = app_state.service.get_task_lists()
                if app_state.task_lists:
                    app_state.change_active_list(app_state.task_lists[0]['id'])
                else:
                    app_state.active_list_id = None
                app_state.refresh_data()

    elif key == ord('p'):
        if ui_manager.active_panel == 'tasks':
            if app_state.tasks:
                current_task = app_state.tasks[ui_manager.selected_task_idx]
                if current_task.get("is_button"):
                    app_state.service.add_task_body(app_state.active_list_id, app_state.task_buffer)
                else:
                    unfiltered_tasks = app_state.service.data['tasks'][app_state.active_list_id]
                    unfiltered_index = -1
                    for i, task in enumerate(unfiltered_tasks):
                        if task['id'] == current_task['id']:
                            unfiltered_index = i
                            break
                    if unfiltered_index != -1:
                        app_state.service.add_task_body(app_state.active_list_id, app_state.task_buffer, unfiltered_index)
                    else:
                        app_state.service.add_task_body(app_state.active_list_id, app_state.task_buffer)
            else:
                app_state.service.add_task_body(app_state.active_list_id, app_state.task_buffer)
            app_state.refresh_data()
        else:
            app_state.service.add_list(app_state.list_buffer)
            app_state.refresh_data()

    elif key == ord('o'):
        if ui_manager.active_panel == 'tasks':
            new_title = ui_manager.get_user_input("New Task Title: ")
            if new_title:
                if app_state.current_parent_task_id:
                    app_state.service.add_task(app_state.active_list_id, new_title, parent=app_state.current_parent_task_id)
                else:
                    app_state.service.add_task(app_state.active_list_id, new_title)
                app_state.refresh_data()
        else:
            new_title = ui_manager.get_user_input("New List Title: ")
            if new_title:
                app_state.service.add_list(new_title)
                app_state.refresh_data()

    elif key == ord('?'):
        ui_manager.toggle_help()

    if app_state.service.dirty:
        _trigger_background_sync(app_state.service, ui_manager)

    return True
def _run_initial_sync(service, result_queue):
    try:
        service.sync_from_google()
        result_queue.put(('ok', None))
    except Exception as exc:
        result_queue.put(('err', str(exc)))

def _trigger_initial_sync(service, ui_manager):
    ui_manager.start_sync_animation()
    threading.Thread(
        target=_run_initial_sync,
        args=(service, _sync_result_queue),
        daemon=True,
    ).start()

def main_loop(stdscr, task_service):
    ui_manager = UIManager(stdscr)
    app_state = AppState(task_service)

    curs_set(0)
    noecho()
    halfdelay(2)
    keypad(stdscr, True)

    _trigger_initial_sync(app_state.service, ui_manager)
    app_state.refresh_data()

    running = True
    while running:
        try:
            result_kind, result_msg = _sync_result_queue.get_nowait()
            ui_manager.stop_sync_animation()
            if result_kind == 'ok':
                app_state.refresh_data()
                if app_state.service.dirty:
                    _trigger_background_sync(app_state.service, ui_manager)
            else:
                app_state.service.sync_from_google()
                app_state.refresh_data()
                ui_manager.show_temporary_message(f"Sync failed (reverted): {result_msg}")
        except queue.Empty:
            pass

        try:
            parent_task = None
            if app_state.current_parent_task_id:
                parent_task = app_state.service.get_task(app_state.active_list_id, app_state.current_parent_task_id)

            parent_ids = app_state.service.get_parent_task_ids(app_state.active_list_id)
            children_counts = app_state.service.get_children_counts(app_state.active_list_id)

            ui_manager.draw_layout(
                app_state.task_lists,
                app_state.tasks,
                app_state.active_list_id,
                app_state.task_counts,
                parent_task=parent_task,
                parent_ids=parent_ids,
                children_counts=children_counts,
                viewing_completed_tasks=app_state.viewing_completed_tasks,
                tasks_due_today=app_state.tasks_due_today
            )
        except Exception as e:
            ui_manager.show_temporary_message(f"Error: {e}")

        running = handle_input(stdscr, app_state, ui_manager)


def cli():
    try:
        task_service = TaskService()
        wrapper(main_loop, task_service)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)


if __name__ == "__main__":
    cli()
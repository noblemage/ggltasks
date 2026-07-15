from unicurses import *
from dateutil.parser import isoparse
import time
import threading


class UIManager:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.setup_colors()
        self.active_panel = "lists"
        self.selected_list_idx = 0
        self.selected_task_idx = 0
        self.selected_due_today_idx = 0
        self.task_scroll_offset = 0
        self.syncing = False
        self.sync_animation_frame = 0
        self.show_help = False

    def setup_colors(self):
        start_color()
        use_default_colors()
        init_pair(1, COLOR_BLACK, COLOR_WHITE)
        init_pair(2, COLOR_GREEN, -1)
        init_pair(3, COLOR_CYAN, -1)
        init_pair(4, COLOR_YELLOW, -1)
        init_pair(5, COLOR_BLUE, -1)

    def _truncate(self, text, max_len):
        if len(text) > max_len:
            if max_len > 3:
                return text[:max_len - 3] + "..."
            return text[:max_len]
        return text

    def _draw_border(self, win, title):
        wborder(win)
        mvwaddstr(win, 0, 2, f" {title} ", color_pair(3) | A_BOLD)

    def draw_layout(self, lists, tasks, active_list_id, task_counts, parent_task=None, parent_ids=None, children_counts=None, viewing_completed_tasks=False, tasks_due_today=None):
        if self.show_help:
            self._draw_help_panel()
            return

        h, w = getmaxyx(self.stdscr)
        list_width = max(25, w // 4)
        task_width = w - list_width

        due_today_height = max(5, h // 3)
        lists_height = h - due_today_height

        list_win = newwin(lists_height, list_width, 0, 0)
        due_today_win = newwin(due_today_height, list_width, lists_height, 0)
        task_win = newwin(h, task_width, 0, list_width)

        self._draw_list_panel(list_win, lists, active_list_id, task_counts)
        self._draw_due_today_panel(due_today_win, tasks_due_today or [])
        self._draw_task_panel(task_win, tasks, parent_task, parent_ids, children_counts, viewing_completed_tasks)

        wrefresh(list_win)
        wrefresh(due_today_win)
        wrefresh(task_win)

        doupdate()

    def _draw_help_panel(self):
        h, w = getmaxyx(self.stdscr)
        help_win = newwin(h, w, 0, 0)
        werase(help_win)
        self._draw_border(help_win, " Help ")
        controls = [
            ("q", "Quit"),             ("o", "Add Task"),
            ("w", "Sync Now"),         ("a", "Set Due Date"),
            ("h/j/k/l", "Navigate"),   ("i", "Edit Notes"),
            ("K/J", "Move Task"),      ("c", "Toggle Done"),
            ("d", "Delete"),           ("X", "Clear Done"),
            ("r", "Rename"),           ("p", "Paste"),
            ("?", "Close Help")
        ]
        
        start_row = (h - 7) // 2
        start_col = (w - 56) // 2
        
        for i, (key, desc) in enumerate(controls):
            row = start_row + (i % 7)
            col = start_col if i < 7 else start_col + 28
            mvwaddstr(help_win, row, col, f"{key:<11}", A_BOLD)
            mvwaddstr(help_win, row, col + 11, desc)
        wrefresh(help_win)

    def _draw_list_panel(self, win, lists, active_list_id, task_counts):
        werase(win)
        self._draw_border(win, "Lists")
        max_y, max_x = getmaxyx(win)
        for idx, list_item in enumerate(lists):
            list_title = list_item.get("title", "Untitled List")
            list_id = list_item.get("id")
            task_count = task_counts.get(list_id, 0)
            is_active = list_item["id"] == active_list_id
            is_selected = self.active_panel == 'lists' and idx == self.selected_list_idx
            y_pos = idx + 1
            if y_pos >= max_y - 1:
                break
            
            attr = A_NORMAL
            if is_active:
                attr |= color_pair(4) | A_BOLD
            if is_selected:
                attr |= color_pair(5)
                
            display_text = f"{list_title} ({task_count})"
            mvwaddstr(win, y_pos, 1, self._truncate(display_text, max_x - 2).ljust(max_x - 2), attr)

    def _draw_due_today_panel(self, win, tasks_due_today):
        werase(win)
        self._draw_border(win, "Due Today")
        max_y, max_x = getmaxyx(win)
        if not tasks_due_today:
            mvwaddstr(win, 1, 2, "Nothing due today", A_DIM)
            return
        for idx, task in enumerate(tasks_due_today):
            y_pos = idx + 1
            if y_pos >= max_y - 1:
                break
            
            is_selected = self.active_panel == 'due_today' and idx == self.selected_due_today_idx
            attr = color_pair(5) if is_selected else A_NORMAL
            
            task_title = task.get('title', 'Untitled')
            list_title = task.get('_list_title', '')
            display = f"{task_title} [{list_title}]"
            display = self._truncate(display, max_x - 2)
            mvwaddstr(win, y_pos, 1, display.ljust(max_x - 2), attr)

    def update_due_today_selection(self, tasks_due_today, direction):
        if self.active_panel != 'due_today' or not tasks_due_today:
            return
        max_idx = len(tasks_due_today) - 1
        new_idx = self.selected_due_today_idx + direction
        if new_idx < 0:
            self.selected_due_today_idx = 0
        elif new_idx > max_idx:
            self.selected_due_today_idx = max_idx
        else:
            self.selected_due_today_idx = new_idx

    def _draw_task_panel(self, win, tasks, parent_task=None, parent_ids=None, children_counts=None, viewing_completed_tasks=False):
        werase(win)
        
        updated_str = ""
        if parent_task and "updated" in parent_task:
            try:
                dt_upd = isoparse(parent_task['updated']).astimezone()
                updated_str = f" [Upd: {dt_upd.strftime('%m-%d %H:%M')}]"
            except ValueError:
                pass
                
        if viewing_completed_tasks:
            title = f"Completed in {parent_task['title']}{updated_str}" if parent_task else "Completed Tasks"
        else:
            title = f"Tasks in {parent_task['title']}{updated_str}" if parent_task else "Tasks"
            
        self._draw_border(win, title)
        max_y, max_x = getmaxyx(win)
        visible_rows = max_y - 2

        if parent_ids is None:
            parent_ids = set()
        if children_counts is None:
            children_counts = {}
        
        if self.syncing:
            braille_patterns = ["⣷", "⣯", "⣟", "⡿", "⢿", "⣻", "⣽", "⣾"]
            anim_char = braille_patterns[self.sync_animation_frame % len(braille_patterns)]
            mvwaddstr(win, max_y - 3, max_x - 15, f" {anim_char} Syncing", A_NORMAL)
            self.sync_animation_frame += 1

        mvwaddstr(win, max_y - 1, max_x - 10, "(?) Help", A_DIM)

        if not tasks:
            attr = color_pair(5) if self.active_panel == 'tasks' else A_DIM
            mvwaddstr(win, 1, 2, "No tasks in this list.", attr)
            return

        if self.selected_task_idx < self.task_scroll_offset:
            self.task_scroll_offset = self.selected_task_idx
        elif self.selected_task_idx >= self.task_scroll_offset + visible_rows:
            self.task_scroll_offset = self.selected_task_idx - visible_rows + 1

        for draw_row, idx in enumerate(range(self.task_scroll_offset, self.task_scroll_offset + visible_rows)):
            if idx >= len(tasks):
                break
            task = tasks[idx]
            task_title = task.get("title", "Untitled Task")
            status = task.get("status", "needsAction")
            is_selected = self.active_panel == 'tasks' and idx == self.selected_task_idx
            y_pos = draw_row + 1

            attr = A_NORMAL
            symbol = "[ ]"
            if task.get("is_button"):
                symbol = "   "
            elif status == "completed":
                attr = color_pair(2)
                symbol = "[X]"
            if is_selected:
                attr = color_pair(5)

            due_date_str = ""
            if "due" in task:
                try:
                    dt = isoparse(task['due'])
                    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                        due_date_str = f" (Due: {dt.strftime('%Y-%m-%d')})"
                    else:
                        due_date_str = f" (Due: {dt.strftime('%Y-%m-%d %H:%M')})"
                except ValueError:
                    due_date_str = " (Invalid Date)"

            note_indicator = "*" if task.get("notes") else " "
            children_count = children_counts.get(task['id'], 0)
            has_children_indicator = f" ({children_count})" if children_count > 0 else ""

            if task.get("is_button"):
                # Center the button text nicely
                title_centered = task_title.center(max_x - 6)
                display_line = f"   {title_centered}"
                mvwaddstr(win, y_pos, 1, self._truncate(display_line, max_x - 2), attr)
            else:
                display_line = f"{symbol} {note_indicator}{task_title}{due_date_str}{has_children_indicator}"
                mvwaddstr(win, y_pos, 1, self._truncate(display_line, max_x - 2), attr)

    def update_task_selection(self, tasks, direction):
        if self.active_panel != 'tasks' or not tasks:
            return
        max_idx = len(tasks) - 1
        new_idx = self.selected_task_idx + direction
        
        while 0 <= new_idx <= max_idx and tasks[new_idx].get("status") == "separator":
            new_idx += direction
            
        if 0 <= new_idx <= max_idx:
            self.selected_task_idx = new_idx

    def reset_task_scroll(self):
        self.selected_task_idx = 0
        self.task_scroll_offset = 0

    def update_list_selection(self, lists, direction):
        if self.active_panel != 'lists' or not lists:
            return
        max_idx = len(lists) - 1
        new_idx = self.selected_list_idx + direction
        if new_idx < 0:
            self.selected_list_idx = 0
        elif new_idx > max_idx:
            self.selected_list_idx = max_idx
        else:
            self.selected_list_idx = new_idx

    def toggle_panel(self):
        # We only toggle between lists/due_today (left) and tasks (right)
        if self.active_panel in ('lists', 'due_today'):
            self.active_panel = 'tasks'
        else:
            self.active_panel = 'lists'

    def toggle_help(self):
        self.show_help = not self.show_help

    def get_confirm_keypress(self, prompt):
        h, w = getmaxyx(self.stdscr)
        full_prompt = f"{prompt} [y/n]: "
        mvwaddstr(self.stdscr, h - 1, 0, full_prompt[:w - 1], A_REVERSE)
        refresh()
        cbreak()
        raw_key = wgetch(self.stdscr)
        halfdelay(2)
        mvwaddstr(self.stdscr, h - 1, 0, " " * min(len(full_prompt) + 1, w - 1))
        refresh()
        if 32 <= raw_key < 127:
            return chr(raw_key).lower()
        return ''

    def get_user_input(self, prompt="Input: ", example=None):
        h, w = getmaxyx(self.stdscr)
        input_win = newwin(1, w, h - 1, 0)
        wmove(input_win, 0, 0)
        waddstr(input_win, prompt, color_pair(0))
        if example:
            example_str = f"(e.g. {example})"
            mvwaddstr(input_win, 0, w - len(example_str) - 1, example_str, A_DIM)
            wmove(input_win, 0, len(prompt))
        wrefresh(input_win)
        input_string = ""
        try:
            keypad(input_win, True)
            echo()
            input_string = wgetstr(input_win)
            noecho()
        finally:
            werase(input_win)
            wrefresh(input_win)
            delwin(input_win)
        if isinstance(input_string, bytes):
            return input_string.decode('utf-8')
        return input_string

    def show_temporary_message(self, message):
        h, w = getmaxyx(self.stdscr)
        mvwaddstr(self.stdscr, h - 2, 1, message, A_REVERSE)
        refresh()
        time.sleep(1)
        mvwaddstr(self.stdscr, h - 2, 1, " " * (len(message) + 1))
        refresh()

    def start_sync_animation(self):
        self.syncing = True

    def stop_sync_animation(self):
        self.syncing = False

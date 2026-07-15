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
        self.task_scroll_offset = 0
        self.syncing = False
        self.animation_thread = None
        self.show_help = False
        self.animation_frame = ""

    def setup_colors(self):
        start_color()
        use_default_colors()
        init_pair(1, COLOR_BLACK, COLOR_WHITE)
        init_pair(2, COLOR_GREEN, -1)
        init_pair(3, COLOR_CYAN, -1)
        init_pair(4, COLOR_YELLOW, -1)
        init_pair(5, COLOR_BLUE, -1)

    def _draw_border(self, win, title):
        wborder(win)
        mvwaddstr(win, 0, 2, f" {title} ", color_pair(3) | A_BOLD)

    def draw_layout(self, lists, tasks, active_list_id, task_counts, parent_task=None, parent_ids=None, children_counts=None, viewing_completed_tasks=False):
        h, w = getmaxyx(self.stdscr)
        list_width = max(25, w // 4)
        task_width = w - list_width
        list_win = newwin(h, list_width, 0, 0)
        task_win = newwin(h, task_width, 0, list_width)
        self._draw_list_panel(list_win, lists, active_list_id, task_counts)
        self._draw_task_panel(task_win, tasks, parent_task, parent_ids, children_counts, viewing_completed_tasks)
        wrefresh(list_win)
        wrefresh(task_win)
        if self.show_help:
            self._draw_help_panel()
        doupdate()

    def _draw_help_panel(self):
        h, w = getmaxyx(self.stdscr)
        help_h, help_w = 15, 60
        help_win = newwin(help_h, help_w, (h - help_h) // 2, (w - help_w) // 2)
        werase(help_win)
        self._draw_border(help_win, "Help (?)")
        controls = [
            ("q", "Quit and Sync"),
            ("w", "Write and Sync"),
            ("h/j/k/l", "Select List/Task/Subtask"),
            ("c", "Complete Toggle"),
            ("r", "Rename Task/List"),
            ("a", "Add Due Date"),
            ("i", "Insert Note"),
            ("d", "Delete Task/List"),
            ("p", "Paste Task/List"),
            ("o", "Open Task"),
            ("?", "Help Toggle"),
        ]
        for i, (key, desc) in enumerate(controls):
            mvwaddstr(help_win, i + 1, 2, f"{key:<20} {desc}")
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
                attr |= color_pair(4)
            if is_selected:
                attr |= color_pair(5)
            mvwaddstr(win, y_pos, 1, f"{list_title} ({task_count})"[:max_x - 2].ljust(max_x - 2), attr)
        mvwaddstr(win, max_y - 1, max_x - 10, "(?) Help", A_DIM)

    def _draw_task_panel(self, win, tasks, parent_task=None, parent_ids=None, children_counts=None, viewing_completed_tasks=False):
        werase(win)
        if viewing_completed_tasks:
            title = f"Completed in {parent_task['title']}" if parent_task else "Completed Tasks"
        else:
            title = f"Tasks in {parent_task['title']}" if parent_task else "Tasks"
        self._draw_border(win, title)
        max_y, max_x = getmaxyx(win)
        visible_rows = max_y - 2

        if parent_ids is None:
            parent_ids = set()
        if children_counts is None:
            children_counts = {}

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
                    due_date_str = f" (Due: {isoparse(task['due']).strftime('%Y-%m-%d')})"
                except ValueError:
                    due_date_str = " (Invalid Date)"

            note_indicator = "*" if task.get("notes") else " "
            children_count = children_counts.get(task['id'], 0)
            has_children_indicator = f" ({children_count})" if children_count > 0 else ""

            display_line = f"{symbol} {note_indicator}{task_title}{due_date_str}{has_children_indicator}"
            mvwaddstr(win, y_pos, 1, display_line[:max_x - 2], attr)

    def update_task_selection(self, tasks, direction):
        if self.active_panel != 'tasks' or not tasks:
            return
        max_idx = len(tasks) - 1
        new_idx = self.selected_task_idx + direction
        if new_idx < 0:
            self.selected_task_idx = 0
        elif new_idx > max_idx:
            self.selected_task_idx = max_idx
        else:
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
        self.active_panel = 'tasks' if self.active_panel == 'lists' else 'lists'

    def toggle_help(self):
        self.show_help = not self.show_help

    def get_user_input(self, prompt="Input: "):
        h, w = getmaxyx(self.stdscr)
        input_win = newwin(1, w, h - 1, 0)
        wmove(input_win, 0, 0)
        waddstr(input_win, prompt, color_pair(0))
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

    def _sync_animation(self):
        braille_patterns = ["⣷", "⣯", "⣟", "⡿", "⢿", "⣻", "⣽", "⣾"]
        i = 0
        h, w = getmaxyx(self.stdscr)
        while self.syncing:
            mvwaddstr(self.stdscr, h - 2, 1, f" {braille_patterns[i % len(braille_patterns)]} Syncing", A_NORMAL)
            refresh()
            time.sleep(0.1)
            i += 1

    def start_sync_animation(self):
        if not self.syncing:
            self.syncing = True
            self.animation_thread = threading.Thread(target=self._sync_animation, daemon=True)
            self.animation_thread.start()

    def stop_sync_animation(self):
        if self.syncing:
            self.syncing = False
            self.animation_thread.join()
            h, w = getmaxyx(self.stdscr)
            mvwaddstr(self.stdscr, h - 2, 1, " " * (w - 2))
            refresh()

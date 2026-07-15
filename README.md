# ggltasks - Google Tasks TUI

A lightning-fast, robust TUI for Google Tasks, built for terminal power users.

## Features

* **Async UI**: Network requests are threaded. The app boots instantly and never freezes.
* **Native Sync**: Moves, completions, and deletions flawlessly sync with the official Google backend.
* **Smart Timestamps**: Due dates and "Last Updated" timestamps.
* **Vim Navigation**: Navigate entirely using `h/j/k/l`.

## Screenshots

<img width="1496" height="951" alt="Image" src="https://github.com/user-attachments/assets/81a03c40-e630-4dbf-b736-c24c8b818b81" />

## Installation

Google requires you to generate a personal "Client Secret" to access your data securely.

### Step 1: Get Google API Credentials
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a **New Project** (e.g., `ggltasks-cli`).
3. Search for **Google Tasks API** and click **Enable**.
4. Go to **APIs & Services → Credentials**.
5. Click **+ CREATE CREDENTIALS** → **OAuth client ID**. *(Choose "Desktop app" as the Application type).*
6. Download the JSON file and rename it exactly to `client_secrets.json`.

### Step 2: Install the App
1. Create a hidden config folder:
   ```bash
   mkdir ~/.ggltasks
   ```
2. Move your `client_secrets.json` file into `~/.ggltasks`.
3. Install via pip:
   ```bash
   pip install ggltasks
   ```
4. Run the app:
   ```bash
   ggltasks
   ```
*Note: The first time you run it, a browser window will pop up asking you to log in to your Google Account. A local token is saved so you only have to do this once.*

## Usage

| Key            | Action                                      |
| :------------- | :------------------------------------------ |
| `q`            | Quit                                        |
| `w`            | Force Sync                                  |
| `↑` / `k`      | Navigate Up                                 |
| `↓` / `j`      | Navigate Down                               |
| `←` / `h`      | Back / Switch Panels                        |
| `→` / `l`      | Enter Subtasks                              |
| `Shift + K`    | Move Task Up                                |
| `Shift + J`    | Move Task Down                              |
| `o`            | Add new task/list                           |
| `d`            | Delete item                                 |
| `r`            | Rename item                                 |
| `c`            | Toggle task completion                      |
| `Shift + X`    | Clear Completed Tasks                       |
| `a`            | Set Due Date                                |
| `i`            | Edit Notes                                  |
| `p`            | Paste deleted task                          |
| `?`            | Toggle Help Menu                            |


### Task Status Symbols

* `[ ]` : Pending
* `[X]` : Completed
* `*` : Has text Note
* `(N)` : Number of direct subtasks
* `[Upd: MM-DD HH:MM]` : Local time the task was last updated

## Known Limitations (Google Tasks API)

These are inherit limitations of the official Google Tasks API backend, not this app:

* **No Times on Due Dates**: The API strips specific hours/minutes off due dates, forcing them to midnight UTC. You can assign a day, but not a time.
* **No Recurring Tasks**: The API does not allow 3rd party apps to create or manage recurring/repeating tasks.
* **Subtask Display Limits**: The API allows infinitely deep subtasks (and this CLI app fully supports them). However, Google's official web/mobile apps will only display 1 level deep. 

## License
MIT License.

# Testing Scotty by hand (about 5 minutes, two PCs)

Automated: `bash scripts/verify.sh` (Git Bash). This is the check only two real PCs can do.

Before: both PCs on the same Wi-Fi set to **Private**, Scotty running on both and paired, keyboard
and mouse connected to PC A only.

| # | Do | Expect |
|---|---|---|
| 1 | Move the pointer off A's screen edge towards B. Type a word in Notepad on B. | The pointer appears on B; the word is typed on B, not A. |
| 2 | On A, copy a 1 GB file in Explorer. Move to B. Keep moving the mouse while it transfers. | The panel on B shows "Receiving…" with progress; A shows "Sending…". The pointer never stutters. |
| 3 | On B, when the panel says it arrived, open Documents and press Ctrl+V. | The file is in Documents. `Downloads\Scotty Drop\<today>` no longer has it. |
| 4 | Press Ctrl+V again in another folder. | Nothing is pasted (it was moved, as after Cut). |
| 5 | On B, copy a folder with subfolders. Move back to A and Ctrl+V. | The whole folder arrives on A with every subfolder. |
| 6 | On A, copy a small `.exe`, send it, paste it on B and double-click it. | Windows warns it came from another computer before it runs. |
| 7 | Copy a file larger than the limit (Overview, Files) and cross. | Nothing is sent; A says it is over the limit and where to raise it. |
| 8 | Start a large transfer and press Cancel on either PC. | Both panels say it stopped; nothing is left in the drop folder. |
| 9 | Turn A's Wi-Fi off during a transfer. | B says the connection was lost; nothing is left behind. |

Report a failure with the step number, what you saw, and `Scotty.log` from each PC
(`%LOCALAPPDATA%\Scotty`, or `data` beside a portable Scotty.exe).

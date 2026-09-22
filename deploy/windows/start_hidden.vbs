' 以隐藏窗口方式启动 ERP 服务 (供开机自启计划任务调用)
Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = dir
WshShell.Run """" & dir & "\.venv\Scripts\python.exe"" -m uvicorn server.app:app --host 0.0.0.0 --port 8000", 0, False

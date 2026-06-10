Set sh = CreateObject("WScript.Shell")
sh.Run "cmd /c cd /d ""C:\innob-agent\prompt-team"" && python app.py", 0, False

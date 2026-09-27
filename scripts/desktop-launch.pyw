"""Double-click launcher; report startup failures even without a console."""
try:
    from local_agent.launcher import main
    main()
except Exception as exc:
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, str(exc), 'Local Agent 启动失败', 0x10)

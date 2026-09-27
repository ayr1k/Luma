"""Windows notification-area lifetime, independent of the page polling loop."""
import threading
import logging

class TrayController:
    def __init__(self, window, shutdown):
        self.window = window
        self.shutdown = shutdown
        self.adapter = None
        self.hidden = False
        self.exiting = False
        self.ready = False
        self.notification_project = None
        self.navigate = None

    def closing(self):
        if self.exiting:
            return
        if not self.ready:
            return False
        self.hidden = True
        self.adapter.hide()
        return False

    def show(self):
        if self.exiting:
            return
        self.hidden = False
        self.adapter.show()

    def show_notification(self):
        self.show()
        if self.notification_project and self.navigate:self.navigate(self.notification_project)

    def completed(self, status, project_id=None):
        if self.adapter and getattr(self.adapter,'features',None):self.adapter.features.completed(status)
        if not self.ready or not self.hidden or self.exiting:
            return
        messages = {'paused': '任务已暂停，点击继续或补充要求。', 'completed': '任务已完成，点击查看结果。',
                    'waiting_approval': '任务需要你的批准，点击查看待审批命令。',
                    'failed': '任务未能完成，点击查看详情。'}
        if status in messages:
            self.notification_project=project_id
            self.adapter.notify(messages[status])

    def exit(self):
        if self.exiting:
            return
        self.exiting = True
        self.adapter.stopping()
        def finish():
            try:
                self.shutdown()
            except Exception:
                logging.exception('Desktop shutdown failed')
                self.exiting = False
                self.adapter.resume()
                self.adapter.notify('退出未完成，请重新尝试。')
                return
            self.adapter.close()
        threading.Thread(target=finish, daemon=False).start()

class WindowsTray:
    def __init__(self, controller, icon_path):
        # pywebview has already initialized the Windows Forms runtime.
        from System import Action
        from System.Drawing import Icon
        from System.Windows.Forms import NotifyIcon, ContextMenuStrip, ToolStripMenuItem, ToolTipIcon, FormWindowState
        self.controller = controller
        self.form = controller.window.native
        self.Action = Action
        self.normal = FormWindowState.Normal
        self.info = ToolTipIcon.Info
        self.icon = Icon(str(icon_path))
        self.tray = NotifyIcon()
        self.menu = ContextMenuStrip()
        self.open_item = ToolStripMenuItem('打开 Luma')
        self.exit_item = ToolStripMenuItem('退出 Luma')
        self.open_item.Click += lambda *_: controller.show()
        self.exit_item.Click += lambda *_: controller.exit()
        self.menu.Items.Add(self.open_item)
        self.menu.Items.Add(self.exit_item)
        self.tray.ContextMenuStrip = self.menu
        self.tray.Text = 'Luma'
        self.tray.Icon = self.icon
        self.tray.DoubleClick += lambda *_: controller.show()
        self.tray.BalloonTipClicked += lambda *_: controller.show_notification()
        self.tray.Visible = True

    def dispatch(self, fn):
        if self.form.InvokeRequired:
            self.form.BeginInvoke(self.Action(fn))
        else:
            fn()

    def hide(self):
        self.dispatch(lambda: self.form.Hide())

    def show(self):
        def action():
            self.form.Show()
            self.form.WindowState = self.normal
            self.form.Activate()
        self.dispatch(action)

    def notify(self, message):
        self.dispatch(lambda: self.tray.ShowBalloonTip(5000, 'Luma', message, self.info))

    def stopping(self):
        def action():
            self.open_item.Enabled = False
            self.exit_item.Enabled = False
            self.tray.Text = 'Luma · 正在安全退出'
        self.dispatch(action)

    def resume(self):
        def action():
            self.open_item.Enabled = True
            self.exit_item.Enabled = True
            self.tray.Text = 'Luma'
        self.dispatch(action)

    def close(self):
        def action():
            self.dispose()
            self.form.Close()
        self.dispatch(action)

    def dispose(self):
        if getattr(self,'features',None):self.features.close()
        self.tray.Visible = False
        self.tray.Dispose()
        self.menu.Dispose()
        self.icon.Dispose()

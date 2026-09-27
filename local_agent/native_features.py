"""Host-owned Windows features selected by declarative software plugins."""
import ctypes
from ctypes import wintypes
import threading

HOTKEYS = {prefix+'+'+key:(modifiers,code) for prefix,modifiers in [('Ctrl+Alt',3),('Ctrl+Shift',6),('Alt+Shift',5)] for key,code in [('L',0x4c),('K',0x4b),('J',0x4a),('Space',0x20),('F8',0x77),('F9',0x78)]}

def clamp_position(x,y,width,height,bounds):
    left,top,right,bottom=bounds
    return max(left,min(x,max(left,right-width))),max(top,min(y,max(top,bottom-height)))

class GlobalHotkey:
    def __init__(self, shortcut, callback):
        if shortcut not in HOTKEYS:raise ValueError('不支持的快捷键')
        self.status='正在注册快捷键';self.thread_id=None;self.stopped=threading.Event()
        self.thread=threading.Thread(target=self._run,args=(shortcut,callback),daemon=True)
        self.thread.start()

    def _run(self, shortcut, callback):
        user=ctypes.WinDLL('user32',use_last_error=True)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        user.RegisterHotKey.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.UINT,wintypes.UINT]
        user.GetMessageW.argtypes=[ctypes.POINTER(wintypes.MSG),wintypes.HWND,wintypes.UINT,wintypes.UINT]
        self.thread_id=kernel.GetCurrentThreadId()
        message=wintypes.MSG()
        # Create a message queue before stop() may post WM_QUIT.
        user.PeekMessageW(ctypes.byref(message),None,0,0,0)
        modifiers,key=HOTKEYS[shortcut]
        if not user.RegisterHotKey(None,1,modifiers|0x4000,key):
            self.status='快捷键不可用或已被占用，请选择其他组合';return
        self.status=shortcut+' · 已注册'
        try:
            while not self.stopped.is_set():
                result=user.GetMessageW(ctypes.byref(message),None,0,0)
                if result<=0:break
                if message.message==0x312 and not self.stopped.is_set():callback()
        finally:
            user.UnregisterHotKey(None,1)

    def close(self):
        self.stopped.set()
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id,0x12,0,0)
        self.thread.join(timeout=2)

class NativeFeatures:
    def __init__(self,controller,data_dir=None):
        from pathlib import Path
        self.position_path=Path(data_dir)/'widget-position.json' if data_dir else None
        self.controller=controller;self.widget=None;self.hotkey=None;self.shortcut=None
        self.status='就绪';self.errors={};self.closed=False

    def snapshot(self):
        return {'widget':self.errors.get('widget','已启用' if self.widget else '未启用'),
                'hotkey':self.errors.get('hotkey',self.hotkey.status if self.hotkey else '未启用')}

    def refresh(self, plugins):
        active={p['contribution']['slot']:p['config'] for p in plugins
                if p.get('enabled') and p.get('category')=='software' and p.get('contribution')}
        self.controller.adapter.dispatch(lambda:self._apply(active))

    def _apply(self,active):
        if self.closed:return
        self.errors={}
        shortcut=active.get('hotkey',{}).get('shortcut')
        if shortcut!=self.shortcut:
            if self.hotkey:self.hotkey.close();self.hotkey=None
            self.shortcut=shortcut
            if shortcut:
                try:self.hotkey=GlobalHotkey(shortcut,self.controller.show)
                except Exception:self.errors['hotkey']='快捷键初始化失败'
        if 'widget' in active:
            try:
                if self.widget is None:self._create_widget()
                self.widget.TopMost=active['widget']['topmost']
                self.label.Text='Luma · '+self.status
            except Exception:self.errors['widget']='悬浮组件初始化失败'
        elif self.widget is not None:
            self.save_position();self.widget.Dispose();self.widget=None

    def completed(self,status):
        self.status={'running':'正在生成…','completed':'任务已完成','waiting_approval':'等待审批',
                     'failed':'任务失败','paused':'任务已暂停','cancelled':'已停止'}.get(status,'就绪')
        if self.widget and not self.closed:
            self.controller.adapter.dispatch(lambda:setattr(self.label,'Text','Luma · '+self.status) if self.widget else None)

    def save_position(self):
        if self.widget is not None and self.position_path:
            from .storage import atomic_json
            try:atomic_json(self.position_path,dict(x=int(self.widget.Left),y=int(self.widget.Top)))
            except OSError:self.errors['widget']='位置保存失败；请检查数据目录权限'

    def _create_widget(self):
        from System.Drawing import Color, Point, Size, Font
        from System.Windows.Forms import Form, FormBorderStyle, FormStartPosition, Label, Button, Screen, MouseButtons
        form=Form();form.Text='Luma 悬浮组件';form.FormBorderStyle=FormBorderStyle.FixedToolWindow
        form.ClientSize=Size(244,92);form.ShowInTaskbar=False;form.MaximizeBox=False;form.MinimizeBox=False
        form.StartPosition=FormStartPosition.Manual
        area=Screen.PrimaryScreen.WorkingArea;x,y=area.Right-270,area.Bottom-135
        if self.position_path and self.position_path.exists():
            import json
            try:
                saved=json.loads(self.position_path.read_text(encoding='utf-8'));x,y=int(saved['x']),int(saved['y'])
                x=max(-100000,min(100000,x));y=max(-100000,min(100000,y))
                area=Screen.FromPoint(Point(x,y)).WorkingArea
            except (ValueError,OSError,KeyError,TypeError):pass
        x,y=clamp_position(x,y,form.Width,form.Height,(area.Left,area.Top,area.Right,area.Bottom))
        form.Location=Point(x,y)
        form.BackColor=Color.FromArgb(36,36,36);form.ForeColor=Color.White
        label=Label();label.Location=Point(12,10);label.Size=Size(220,23);label.Text='Luma · '+self.status
        button=Button();button.Text='打开 Luma';button.Location=Point(12,43);button.Size=Size(220,32)
        button.Click+=lambda *_:self.controller.show()
        self.drag=None
        def down(sender,event):
            if event.Button==MouseButtons.Left:self.drag=Point(event.X,event.Y)
        def move(sender,event):
            if event.Button==MouseButtons.Left and self.drag is not None:
                form.Location=Point(form.Left+event.X-self.drag.X,form.Top+event.Y-self.drag.Y)
        label.MouseDown+=down;label.MouseMove+=move
        label.MouseUp+=lambda *_:self.save_position()
        form.ResizeEnd+=lambda *_:self.save_position()
        def closing(sender,event):
            # X returns focus to the main app; disable the feature in Extension Center.
            event.Cancel=True;self.controller.show()
        form.FormClosing+=closing
        form.Controls.Add(label);form.Controls.Add(button)
        self.widget=form;self.label=label;form.Show()

    def close(self):
        self.closed=True
        if self.hotkey:self.hotkey.close();self.hotkey=None
        if self.widget:self.save_position();self.widget.Dispose();self.widget=None

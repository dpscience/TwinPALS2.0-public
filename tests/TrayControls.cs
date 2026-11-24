// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using System.Windows.Forms;

// Build alongside the production source with /main:TrayControls. Render the same
// Windows controls offscreen so the test never captures other applications.
internal class TrayControls {
    [DllImport("user32.dll")]
    static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")]
    static extern bool PostMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")]
    static extern bool GetClientRect(IntPtr window, out Rectangle bounds);

    // Drive the WinForms notification window of this isolated test instance.
    // The helper type and its menu come from the packaged executable.
    static void CheckPopupButtons(string output,string helper) {
        string dir=Path.Combine(output,Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        var process=Process.GetCurrentProcess();
        Func<string,string,string> register=(role,activity)=>{
            string file=Path.Combine(dir,Guid.NewGuid().ToString("N")+".json");
            File.WriteAllText(file,new JavaScriptSerializer().Serialize(new {role,activity,phase="Ready",port=role=="desktop"?18622:53715,
                pid=process.Id,birth=process.StartTime.ToUniversalTime().ToFileTimeUtc().ToString(),exe=helper,data=dir}));
            return file;
        };
        string desktop=register("desktop","Module 1, Module 2, Module 3 active");
        var type=Assembly.LoadFile(Path.GetFullPath(helper)).GetType("TrayContext",true);
        var hidden=BindingFlags.NonPublic | BindingFlags.Instance;
        using (var context=(ApplicationContext)Activator.CreateInstance(type,hidden,null,new object[]{dir},null)) {
            try {
                var icon=(NotifyIcon)type.GetField("icon",hidden).GetValue(context);
                var menu=(ContextMenuStrip)type.GetField("menu",hidden).GetValue(context);
                var fields=typeof(NotifyIcon).GetFields(hidden);
                var receiver=(NativeWindow)fields.Single(f=>typeof(NativeWindow).IsAssignableFrom(f.FieldType)).GetValue(icon);
                var id=new IntPtr(Convert.ToInt32(fields.Single(f=>f.Name.TrimStart('_')=="id").GetValue(icon)));
                int callback=(int)typeof(NotifyIcon).GetField("WM_TRAYMOUSEMESSAGE",BindingFlags.NonPublic|BindingFlags.Static).GetRawConstantValue();
                foreach (string mode in new[]{"desktop","combined","mcp"}) {
                    if (mode=="combined") register("mcp","2 active study steps");
                    if (mode=="mcp") File.Delete(desktop);
                    string[] expected=mode=="desktop" ? new[]{"Open desktop in browser","Status and paths…","Stop desktop service…"} :
                        mode=="mcp" ? new[]{"Open study observer","Status and paths…","Stop MCP service…"} :
                        new[]{"Open desktop in browser","Open study observer","Status and paths…","Stop desktop service…","Stop MCP service…"};
                    Size first=Size.Empty;
                    foreach (bool left in new[]{true,false}) {
                        SendMessage(receiver.Handle,callback,id,new IntPtr(left?0x201:0x204));
                        SendMessage(receiver.Handle,callback,id,new IntPtr(left?0x202:0x205));
                        Application.DoEvents();
                        if (!menu.Visible || !menu.Items.OfType<ToolStripMenuItem>().Select(i=>i.Text).SequenceEqual(expected))
                            throw new InvalidOperationException("Unexpected opened popup: "+mode+" "+left);
                        Rectangle client;
                        if (!GetClientRect(menu.Handle,out client) || client.Size!=menu.ClientSize ||
                            (!left && client.Size!=first)) throw new InvalidOperationException("Popup size changed between clicks.");
                        var headings=menu.Items.OfType<ToolStripLabel>().ToArray();
                        if (headings.Length!=(mode=="combined"?2:1) || (mode!="mcp" && !headings.Any(h=>h.Text.Contains("Module 3 active"))))
                            throw new InvalidOperationException("Active status missing from popup.");
                        if ((mode!="mcp" && !headings.Any(h=>h.Text.Contains("127.0.0.1:18622"))) ||
                            (mode!="desktop" && !headings.Any(h=>h.Text.Contains("127.0.0.1:53715"))))
                            throw new InvalidOperationException("Service address missing from popup.");
                        foreach (var heading in headings)
                            if (heading.Width<heading.GetPreferredSize(Size.Empty).Width || heading.Bounds.Right>client.Width)
                                throw new InvalidOperationException("Native popup clips "+heading.Text+"; row "+heading.Bounds+
                                    ", preferred "+heading.GetPreferredSize(Size.Empty)+", native client "+client.Size);
                        first=client.Size;
                        string snapshot=Path.Combine(output,mode+(left?"-left.png":"-right.png"));
                        Save(menu,snapshot);
                        if (!left && !File.ReadAllBytes(snapshot).SequenceEqual(File.ReadAllBytes(Path.Combine(output,mode+"-left.png"))))
                            throw new InvalidOperationException("Left and right rendered different menus for "+mode);
                        PostMessage(menu.Handle,0x100,new IntPtr((int)Keys.Escape),IntPtr.Zero);
                        Application.DoEvents();
                        if(menu.Visible) throw new InvalidOperationException("Escape did not dismiss the popup.");
                    }
                }
                if (Directory.GetFiles(dir,"*.cmd").Length!=0)
                    throw new InvalidOperationException("Opening the popup issued a service command.");
            } finally { context.ExitThread(); }
        }
    }
    static void Save(Control view,string file) {
        using(Bitmap image=new Bitmap(view.Width,view.Height)) {
            view.DrawToBitmap(image,new Rectangle(Point.Empty,image.Size));
            image.Save(file,ImageFormat.Png);
        }
    }

    static void CheckMenu(IList<TrayEntry> entries, string output, string name) {
        using (var menu = new ContextMenuStrip()) {
            var actions = new List<string>();
            TrayContext.FillMenu(menu, entries, (r,a,s)=>actions.Add(r.role+"."+a), ()=>actions.Add("paths"));
            menu.CreateControl();
            menu.PerformLayout();
            var headers=menu.Items.OfType<ServiceHeading>().ToArray();
            if (headers.Length!=entries.Count || headers.Any(i=>i.CanSelect || i.AccessibleRole!=AccessibleRole.StaticText))
                throw new InvalidOperationException("Service status must be readable and outside keyboard navigation.");
            if (!menu.Items.OfType<ToolStripMenuItem>().All(i=>!String.IsNullOrEmpty(i.Text)))
                throw new InvalidOperationException("Unlabelled command.");
            foreach (var header in headers)
                if (header.Width<header.GetPreferredSize(Size.Empty).Width || header.Bounds.Right>menu.ClientSize.Width)
                    throw new InvalidOperationException("Clipped service heading: "+header.Text);
            var next=menu.GetNextItem(null,ArrowDirection.Down);
            if (next is ServiceHeading)
                throw new InvalidOperationException("Keyboard focus reached a service heading: "+next.Text);
            Save(menu,Path.Combine(output,name));
            foreach (var action in menu.Items.OfType<ToolStripMenuItem>().Where(i=>i.Enabled)) action.PerformClick();
            var ready=entries.Where(r=>r.phase=="Ready").ToArray();
            var expected=ready.Select(r=>r.role+".open").Concat(new[]{"paths"}).Concat(ready.Select(r=>r.role+".stop"));
            if (!actions.SequenceEqual(expected)) throw new InvalidOperationException("Unexpected menu command order.");
        }
    }

    [STAThread] static int Main(string[] args) {
        try { return Check(args); }
        catch (Exception error) {
            if (args.Length>0 && Directory.Exists(args[0]))
                File.WriteAllText(Path.Combine(args[0],"tray-controls-error.log"),error.ToString());
            return 1;
        }
    }

    static int Check(string[] args) {
        if(args[0].StartsWith("http://127.0.0.1:")) {
            var uri=new Uri(args[0]);
            File.AppendAllText(Environment.GetEnvironmentVariable("TRAY_TEST_OPENED"),
                uri.AbsolutePath+uri.Query+" "+(uri.Fragment.Length>1?"viewer":"desktop")+Environment.NewLine);
            return 0;
        }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string output=args[0];
        Directory.CreateDirectory(output);
        if(args.Length==3 && args[1]=="--popup") {
            CheckPopupButtons(output,args[2]);
            return 0;
        }
        var entries=args.Length>1 ? TrayContext.ReadEntries(args[1]) : new List<TrayEntry> {
            new TrayEntry {role="desktop",phase="Ready",port=18622,exe=@"D:\TwinPALS\TwinPALS.exe",data=@"D:\TwinPALS\data"},
            new TrayEntry {role="mcp",phase="Ready",port=53715,activity="2 active study steps",exe=@"D:\TwinPALS\TwinPALS-MCP.exe",data=@"D:\TwinPALS\data"}
        };
        if(args.Length==3) {
            using(var menu=new ContextMenuStrip()) {
                TrayContext.FillMenu(menu,entries,TrayContext.Publish,()=>{});
                var item=menu.Items.OfType<ToolStripMenuItem>().Single(i=>i.Text==args[2]);
                if(!item.Enabled) return 8;
                item.PerformClick();
            }
            return 0;
        }
        if(entries.Count!=2 || !entries[0].Desktop || entries[1].Desktop) return 1;
        CheckMenu(entries,output,"tray-menu.png");
        CheckMenu(entries.Take(1).ToList(),output,"tray-desktop.png");
        CheckMenu(entries.Skip(1).ToList(),output,"tray-mcp.png");
        entries[0].phase="Starting";
        CheckMenu(entries.Take(1).ToList(),output,"tray-starting.png");
        entries[0].phase="Ready";
        using(var form=new Form()) {
            form.Text="TwinPALS 2.0 · Status and paths";
            form.Font=SystemFonts.MessageBoxFont; form.ClientSize=new Size(685,380);
            var body=TrayContext.DetailBody(entries);
            form.BackColor=Color.White; form.Controls.Add(body);
            form.StartPosition=FormStartPosition.Manual; form.Location=new Point(-30000,-30000);
            form.ShowInTaskbar=false; form.Show(); Application.DoEvents();
            var cards=body.Controls.OfType<TableLayoutPanel>().ToArray();
            for(int i=0;i<entries.Count;i++) {
                if(!cards[i].Controls.OfType<TextBox>().Any(box=>box.ReadOnly && box.Text==entries[i].Address))
                    throw new InvalidOperationException("Missing address in Status and paths.");
                if(!entries[i].Desktop && !cards[i].Controls.OfType<TextBox>().Any(box=>box.Text=="stdio"))
                    throw new InvalidOperationException("Missing MCP transport in Status and paths.");
            }
            Save(form,Path.Combine(output,"tray-paths.png"));
        }
        return 0;
    }
}

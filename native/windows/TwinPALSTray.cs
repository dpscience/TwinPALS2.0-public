// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal class TrayNotice {
    public string id { get; set; }
    public string kind { get; set; }
    public string study { get; set; }
    public string title { get; set; }
}

internal class TrayEntry {
    public string key, file;
    public string role { get; set; }
    public int pid { get; set; }
    public int port { get; set; }
    public string birth { get; set; }
    public string phase { get; set; }
    public string data { get; set; }
    public string exe { get; set; }
    public string activity { get; set; }
    public TrayNotice notice { get; set; }
    public bool Desktop { get { return role == "desktop"; } }
    public string Name { get { return Desktop ? "Desktop" : "MCP study service"; } }
    public string Status { get { return String.IsNullOrEmpty(activity) ? phase : activity; } }
    public string Address { get { return port > 0 && port <= 65535 ? "127.0.0.1:" + port : "Address unavailable"; } }
}

// The service and its state share one read-only row. Only commands take focus.
internal sealed class ServiceHeading : ToolStripLabel {
    readonly string service, state, address;
    readonly bool ready, busy;
    readonly int inset, gap, dot;
    readonly Font headingFont;
    static readonly TextFormatFlags Metrics = TextFormatFlags.NoPadding | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine;

    internal ServiceHeading(TrayEntry entry, bool showPid, int unit, Font bold) {
        service = entry.Name + (showPid ? " (PID " + entry.pid + ")" : "");
        state = entry.Status;
        address = (entry.Desktop ? "Desktop UI" : "Observer") + "  ·  " + entry.Address;
        ready = entry.phase == "Ready";
        busy = !String.IsNullOrEmpty(entry.activity);
        inset = unit;
        gap = unit * 2;
        dot = Math.Max(4, unit / 2);
        headingFont = bold;
        Text = service + ", " + state + ", " + address;
        AccessibleRole = AccessibleRole.StaticText;
        AccessibleName = Text;
        Margin = Padding.Empty;
    }

    public override bool CanSelect { get { return false; } }

    public override Size GetPreferredSize(Size proposed) {
        Size nameSize = TextRenderer.MeasureText(service, headingFont, Size.Empty, Metrics);
        Size stateSize = TextRenderer.MeasureText(state, Font, Size.Empty, Metrics);
        Size addressSize = TextRenderer.MeasureText(address, Font, Size.Empty, Metrics);
        int contentWidth = Math.Max(addressSize.Width, nameSize.Width + gap + dot * 2 + stateSize.Width);
        int width = Math.Max(18 * inset, 2 * inset + contentWidth);
        return new Size(width, Math.Max(nameSize.Height, stateSize.Height) + addressSize.Height + 4 * inset / 3);
    }

    protected override void OnPaint(PaintEventArgs e) {
        bool contrast = SystemInformation.HighContrast;
        Color ink = contrast ? SystemColors.MenuText : Color.FromArgb(35, 61, 78);
        Color status = contrast ? SystemColors.MenuText : Color.FromArgb(69, 95, 108);
        Color mark = contrast ? status : ready ? (busy ? Color.SteelBlue : Color.Teal) : Color.DarkGoldenrod;
        Size stateSize = TextRenderer.MeasureText(e.Graphics, state, Font, Size.Empty, Metrics);
        // WinForms can inset a label again when reopening a dropdown. Anchor both
        // columns to the visible menu, independently of the row's layout offset.
        int left = inset - Bounds.Left;
        int x = (Parent == null ? Width : Parent.ClientSize.Width) - Bounds.Left - inset - stateSize.Width;
        var alignment = Metrics | TextFormatFlags.VerticalCenter;
        int top = inset / 2;
        int line = Math.Max(headingFont.Height, Font.Height);
        TextRenderer.DrawText(e.Graphics, service, headingFont, new Rectangle(left, top, x - dot * 2 - left, line), ink, alignment);
        TextRenderer.DrawText(e.Graphics, state, Font, new Rectangle(x, top, stateSize.Width, line), status, alignment);
        TextRenderer.DrawText(e.Graphics, address, Font, new Rectangle(left, top + line + inset / 3, Width - left, Font.Height), status, alignment);
        using (var brush = new SolidBrush(mark)) {
            var previous = e.Graphics.SmoothingMode;
            e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            e.Graphics.FillEllipse(brush, x - dot * 2, top + (line - dot) / 2, dot, dot);
            e.Graphics.SmoothingMode = previous;
        }
    }
}

internal sealed class TrayMenuRenderer : ToolStripProfessionalRenderer {
    readonly int inset;
    internal TrayMenuRenderer(int inset) { this.inset = inset; RoundedEdges = false; }

    protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e) {
        if (e.Item is ToolStripMenuItem) {
            e.TextRectangle = new Rectangle(inset, 0, e.Item.Width - 2 * inset, e.Item.Height);
            e.TextFormat |= TextFormatFlags.NoPadding;
        }
        base.OnRenderItemText(e);
    }

    protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e) {
        int y = e.Item.Height / 2;
        using (var pen = new Pen(SystemInformation.HighContrast ? SystemColors.MenuText : Color.FromArgb(210, 221, 226)))
            e.Graphics.DrawLine(pen, inset, y, e.Item.Width - inset - 1, y);
    }
}

internal sealed class TrayContext : ApplicationContext {
    static readonly Color Ink = Color.FromArgb(28,56,75), Teal = Color.FromArgb(12,115,119);
    static readonly Font Heading = new Font(SystemFonts.MessageBoxFont,FontStyle.Bold);
    static readonly Font MenuHeading = new Font(SystemFonts.MenuFont, FontStyle.Bold);
    readonly string directory;
    readonly NotifyIcon icon;
    readonly Icon artwork;
    readonly ContextMenuStrip menu = new ContextMenuStrip();
    readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer();
    readonly Dictionary<string,string> seen = new Dictionary<string,string>();
    List<TrayEntry> entries = new List<TrayEntry>();
    DateTime lastLive = DateTime.UtcNow;
    TrayEntry lastNotice;
    string lastStudy;
    Form details;
    string detailsState;

    internal TrayContext(string folder) {
        directory = folder;
        artwork = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        icon = new NotifyIcon { Icon=artwork, Text="TwinPALS 2.0" };
        icon.MouseUp += (s,e) => {
            if (e.Button == MouseButtons.Left || e.Button == MouseButtons.Right) ShowTrayMenu();
        };
        icon.BalloonTipClicked += (s,e) => { if(lastNotice!=null) Publish(lastNotice,"open",lastStudy); };
        timer.Interval=800;
        timer.Tick += (s,e) => RefreshEntries();
        RefreshEntries();
        timer.Start();
    }

    [DllImport("user32.dll")]
    static extern bool SetForegroundWindow(IntPtr window);

    void ShowTrayMenu() {
        if (menu.Visible) return;
        RefreshEntries();
        if (entries.Count == 0) return;
        FillMenu(menu, entries, Publish, ShowDetails);
        Point anchor = Cursor.Position;
        Rectangle area = Screen.FromPoint(anchor).WorkingArea;
        int x = anchor.X + menu.Width <= area.Right ? anchor.X : anchor.X - menu.Width;
        int y = anchor.Y + menu.Height + 1 <= area.Bottom ? anchor.Y + 1 : anchor.Y - menu.Height - 1;
        menu.Show(new Point(Math.Max(area.Left, Math.Min(x, area.Right - menu.Width)),
                            Math.Max(area.Top, Math.Min(y, area.Bottom - menu.Height))));
        SetForegroundWindow(menu.Handle);
    }

    internal static List<TrayEntry> ReadEntries(string folder) {
        var result=new List<TrayEntry>();
        if(!Directory.Exists(folder)) return result;
        foreach(string path in Directory.GetFiles(folder,"*.json")) {
            Guid id;
            string key=Path.GetFileNameWithoutExtension(path);
            if(!Guid.TryParseExact(key,"N",out id)) continue;
            try {
                TrayEntry entry;
                using(var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete))
                using(var reader=new StreamReader(stream)) {
                    if(stream.Length>65536) continue;
                    entry=new JavaScriptSerializer().Deserialize<TrayEntry>(reader.ReadToEnd());
                }
                if(entry==null || (entry.role!="desktop" && entry.role!="mcp") || String.IsNullOrEmpty(entry.data)) continue;
                bool live=false;
                try {
                    using(Process p=Process.GetProcessById(entry.pid))
                        live=p.SessionId==Session && p.StartTime.ToUniversalTime().ToFileTimeUtc().ToString(CultureInfo.InvariantCulture)==entry.birth;
                } catch(ArgumentException) {} catch(InvalidOperationException) {}
                if(!live) {
                    File.Delete(path);
                    foreach(string cmd in Directory.GetFiles(folder,key+".*.cmd")) File.Delete(cmd);
                    continue;
                }
                entry.key=key; entry.file=path; result.Add(entry);
            } catch(IOException) {} catch(UnauthorizedAccessException) {} catch(ArgumentException) {}
              catch(InvalidOperationException) {} catch(System.ComponentModel.Win32Exception) {}
        }
        return result.OrderBy(r=>r.Desktop?0:1).ThenBy(r=>r.data).ToList();
    }

    internal static readonly int Session=Process.GetCurrentProcess().SessionId;

    void RefreshEntries() {
        try { entries=ReadEntries(directory); } catch(IOException) { return; } catch(UnauthorizedAccessException) { return; }
        if(entries.Count==0) {
            icon.Visible=false;
            if((DateTime.UtcNow-lastLive).TotalSeconds>3) ExitThread();
            return;
        }
        lastLive=DateTime.UtcNow;
        icon.Visible=true;
        string tip="TwinPALS 2.0\n"+String.Join("\n",entries.Select(r=>r.Name+" · "+r.Status));
        icon.Text=tip.Substring(0,Math.Min(63,tip.Length));
        foreach(TrayEntry r in entries) {
            string old;
            if(r.notice==null || (seen.TryGetValue(r.key,out old) && old==r.notice.id)) continue;
            seen[r.key]=r.notice.id;
            lastNotice=r; lastStudy=r.notice.study;
            bool failed=r.notice.kind=="failed";
            icon.ShowBalloonTip(6000,failed?"TwinPALS · Study needs attention":"TwinPALS · Study started",
                r.notice.title+"\nOpen the study observer",failed?ToolTipIcon.Warning:ToolTipIcon.Info);
        }
        if(details!=null && !details.IsDisposed) UpdateDetails();
    }

    static void Command(ContextMenuStrip target,string label,EventHandler click,int inset,bool enabled=true) {
        var item=new ToolStripMenuItem(label);
        item.ForeColor=SystemInformation.HighContrast ? SystemColors.MenuText : Ink;
        item.Padding=new Padding(0, inset / 3, 0, inset / 3);
        item.Enabled=enabled;
        item.Click+=click;
        target.Items.Add(item);
    }

    internal static void FillMenu(ContextMenuStrip target,IList<TrayEntry> list,Action<TrayEntry,string,string> send,Action status) {
        target.SuspendLayout();
        try {
            while (target.Items.Count>0) target.Items[0].Dispose();
            target.AutoSize=false;
            target.ShowImageMargin=false;
            target.ShowCheckMargin=false;
            target.Font=SystemFonts.MenuFont;
            int inset=Math.Max(12, target.Font.Height - 3);
            target.Padding=new Padding(2, inset / 3, 2, inset / 3);
            target.Renderer=new TrayMenuRenderer(inset);
            foreach (TrayEntry entry in list) {
                if (target.Items.Count>0) target.Items.Add(new ToolStripSeparator());
                target.Items.Add(new ServiceHeading(entry, list.Count(other=>other.role==entry.role)>1, inset, MenuHeading));
                bool enabled=entry.phase=="Ready";
                Command(target, entry.Desktop ? "Open desktop in browser" : "Open study observer",
                        (s,e)=>send(entry,"open",""), inset, enabled);
            }
            target.Items.Add(new ToolStripSeparator());
            Command(target,"Status and paths…",(s,e)=>status(),inset);
            target.Items.Add(new ToolStripSeparator());
            foreach (TrayEntry entry in list) {
                string label = entry.Desktop ? "Stop desktop service" : "Stop MCP service";
                if (list.Count(other=>other.role==entry.role)>1) label += " (PID " + entry.pid + ")";
                Command(target, label + "…", (s,e)=>send(entry,"stop",""), inset, entry.phase=="Ready");
            }
        } finally { target.ResumeLayout(true); }
        // Fix the native popup size before Show, including headings which
        // WinForms otherwise shrinks to individual labels when it reopens.
        Size preferred = target.GetPreferredSize(Size.Empty);
        var headings = target.Items.OfType<ServiceHeading>().ToArray();
        int headingWidth = headings.Select(h=>h.GetPreferredSize(Size.Empty).Width).DefaultIfEmpty().Max();
        target.Size = new Size(Math.Max(preferred.Width, headingWidth + target.Padding.Horizontal), preferred.Height);
        foreach (var row in headings) {
            row.AutoSize = false;
            row.Size = new Size(target.DisplayRectangle.Width, row.GetPreferredSize(Size.Empty).Height);
        }
    }

    internal static void Publish(TrayEntry entry,string action,string study) {
        if(!File.Exists(entry.file)) return;
        string stem=Path.Combine(Path.GetDirectoryName(entry.file),entry.key+"."+Guid.NewGuid().ToString("N"));
        try {
            File.WriteAllText(stem+".tmp",new JavaScriptSerializer().Serialize(new { action=action, study=study??"" }),new UTF8Encoding(false));
            File.Move(stem+".tmp",stem+".cmd");
        } catch(IOException) {} catch(UnauthorizedAccessException) {}
    }

    internal static Control DetailBody(IList<TrayEntry> list) {
        var body=new TableLayoutPanel { Dock=DockStyle.Top, AutoSize=true, ColumnCount=1,
            Padding=new Padding(20,14,20,16), BackColor=Color.White };
        body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
        foreach(TrayEntry r in list) {
            var card=new TableLayoutPanel { Dock=DockStyle.Top,AutoSize=true,ColumnCount=2,
                Padding=new Padding(12),Margin=new Padding(0,0,0,10),BackColor=Color.FromArgb(241,247,247) };
            card.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
            var title=new Label { Text=r.Name+"   ·   "+r.Status, ForeColor=Teal, AutoSize=true,
                Font=Heading,Margin=new Padding(0,0,0,10) };
            card.Controls.Add(title,0,0); card.SetColumnSpan(title,2);
            string[] labels=r.Desktop ? new[]{"Desktop UI","Executable","Database"} : new[]{"Observer","MCP transport","Executable","Database"};
            string[] values=r.Desktop ? new[]{r.Address,r.exe,Path.Combine(r.data,"catalogue.tpdb")} :
                new[]{r.Address,"stdio",r.exe,Path.Combine(r.data,"catalogue.tpdb")};
            for(int i=0;i<labels.Length;i++) {
                card.Controls.Add(new Label { Text=labels[i],ForeColor=Ink,AutoSize=true,Margin=new Padding(0,4,16,4) },0,i+1);
                card.Controls.Add(new TextBox { Text=values[i],ReadOnly=true,Dock=DockStyle.Fill,
                    BorderStyle=BorderStyle.None,BackColor=card.BackColor,ForeColor=Ink,Margin=new Padding(0,4,0,4) },1,i+1);
            }
            body.Controls.Add(card);
        }
        return body;
    }

    void UpdateDetails() {
        string fingerprint=String.Join("\n",entries.Select(r=>r.key+"\t"+r.Status+"\t"+r.Address));
        if(fingerprint==detailsState) return;
        detailsState=fingerprint;
        details.SuspendLayout();
        while(details.Controls.Count>0) details.Controls[0].Dispose();
        details.Controls.Add(DetailBody(entries));
        details.ResumeLayout(true);
    }

    void ShowDetails() {
        if(details==null || details.IsDisposed) {
            details=new Form { Text="TwinPALS 2.0 · Status and paths", Icon=artwork, AutoScroll=true, BackColor=Color.White,
                StartPosition=FormStartPosition.CenterScreen, ClientSize=new Size(690,Math.Min(600,175*entries.Count+30)),
                MinimumSize=new Size(440,180), Font=SystemFonts.MessageBoxFont };
            detailsState=null;
        }
        UpdateDetails(); details.Show(); details.WindowState=FormWindowState.Normal; details.Activate();
    }

    protected override void ExitThreadCore() {
        timer.Stop(); timer.Dispose(); icon.Visible=false; icon.Dispose(); menu.Dispose();
        if(details!=null) details.Dispose(); artwork.Dispose(); base.ExitThreadCore();
    }

    [STAThread] static void Main() {
        string basePath=Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if(String.IsNullOrEmpty(basePath)||Session==0) return;
        string directory=Path.Combine(basePath,"TwinPALS","Tray",Session.ToString());
        bool first;
        using(var mutex=new Mutex(true,@"Local\TwinPALS.Tray."+Session+"."+Namespace(directory),out first)) {
            if(!first) return;
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            Directory.CreateDirectory(directory);
            string pidFile=Path.Combine(directory,"host.pid");
            File.WriteAllText(pidFile,Process.GetCurrentProcess().Id.ToString(CultureInfo.InvariantCulture));
            try { using(var context=new TrayContext(directory)) Application.Run(context); }
            finally { File.Delete(pidFile); }
        }
    }

    internal static string Namespace(string path) {
        using(var sha=System.Security.Cryptography.SHA256.Create())
            return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(path).ToUpperInvariant()))).Replace("-","").Substring(0,16);
    }
}

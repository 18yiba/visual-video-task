using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;
using System.Threading;

class Launcher {
    static string Quote(string value) {
        var b=new StringBuilder("\""); int slashes=0;
        foreach(char c in value) {
            if(c=='\\') {slashes++;continue;}
            if(c=='"') {b.Append('\\',slashes*2+1);b.Append(c);slashes=0;continue;}
            b.Append('\\',slashes);slashes=0;b.Append(c);
        }
        b.Append('\\',slashes*2);return b.Append('"').ToString();
    }
    [STAThread]
    static int Main(string[] args) {
        try {
            using(var mutex=new Mutex(false,"VisualVideoTask.Desktop")) {
            if(!mutex.WaitOne(0,false)) {MessageBox.Show("视频EEG程序已经运行，请完成并保存当前采集。","视频EEG");return 1;}
            string root=AppDomain.CurrentDomain.BaseDirectory;
            var start=new ProcessStartInfo(Path.Combine(root,"runtime","python.exe"));
            var arguments=new StringBuilder("-I -B -X utf8 ");
            arguments.Append(Quote(Path.Combine(root,"app","scripts","desktop_entry.py")));
            foreach(string arg in args) arguments.Append(" ").Append(Quote(arg));
            start.Arguments=arguments.ToString();start.WorkingDirectory=root;
            start.UseShellExecute=false;start.CreateNoWindow=true;start.WindowStyle=ProcessWindowStyle.Hidden;
            start.EnvironmentVariables.Remove("PYTHONHOME");start.EnvironmentVariables.Remove("PYTHONPATH");
            using(var process=Process.Start(start)) {process.WaitForExit();return process.ExitCode;}
            }
        } catch(Exception e) {
            MessageBox.Show("启动未完成，请保留安装目录并重新运行安装包。\n"+e.Message,"视频EEG",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        }
    }
}

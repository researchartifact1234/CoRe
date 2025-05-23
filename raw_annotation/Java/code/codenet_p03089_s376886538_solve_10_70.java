import java.io.*;
import java.util.*;
import java.math.*;
public class Main {
    InputStream is;
    PrintWriter out;
    String INPUT = "";
    static int mod = 1_000_000_007;
    long inf = Long.MAX_VALUE/2;
    void solve(){
        int n = ni();
        int[] a = new int[n];
        for(int i = 0; i < n; i++){
            a[i] = ni();
        }
        boolean[] seen = new boolean[n];
        ArrayList<Integer> ans = new ArrayList<>();
        int t = 1;
        int l = 0;
        int r = n-1;
        while(true){
            outer:
            for(int i = n-1; i >= 0; i--){
                if(seen[i]) continue;
                if(i<l){
                    out.println(-1);
                    return;
                }
                if(a[i]==t){
                    seen[i] = true;
                    ans.add(a[i]);
                    boolean flag = true;
                    for(int j = i+1; j < n; j++){
                        if(!seen[j]){
                            flag = false;
                        }
                    }
                    if(flag){
                        break;
                    }
                    else{
                        t++;
                        i = n;
                        continue;
                    }
                }
            }
            if(!seen[n-1]){
                out.println(-1);
                return;
            }
            boolean flag = true;
            for(int i = n-1; i >= 0; i--){
                if(!seen[i]){
                    t = a[i+1];
                    flag = false;
                    r = i;
                    for(int j = i; j >= 0; j--){
                        if(seen[j]) break;
                        l = j;
                    }
                    break;
                }
            }
            if(flag) break;
        }
        for(int i : ans){
            out.println(i);
        }
    }
    void run() throws Exception
    {
        is = INPUT.isEmpty() ? System.in : new ByteArrayInputStream(INPUT.getBytes());
        out = new PrintWriter(System.out);
        long s = System.currentTimeMillis();
        solve();
        out.flush();
        if(!INPUT.isEmpty())tr(System.currentTimeMillis()-s+"ms");
    }
    public static void main(String[] args) throws Exception { new Main().run(); }
    private byte[] inbuf = new byte[1024];
    private int lenbuf = 0, ptrbuf = 0;
    private int readByte()
    {
        if(lenbuf == -1)throw new InputMismatchException();
        if(ptrbuf >= lenbuf){
            ptrbuf = 0;
            try { lenbuf = is.read(inbuf); } catch (IOException e) { throw new InputMismatchException(); }
            if(lenbuf <= 0)return -1;
        }
        return inbuf[ptrbuf++];
    }
    private boolean isSpaceChar(int c) { return !(c >= 33 && c <= 126); }
    private int skip() { int b; while((b = readByte()) != -1 && isSpaceChar(b)); return b; }
    private double nd() { return Double.parseDouble(ns()); }
    private char nc() { return (char)skip(); }
    private String ns()
    {
        int b = skip();
        StringBuilder sb = new StringBuilder();
        while(!(isSpaceChar(b) && b != ' ')){
            sb.appendCodePoint(b);
            b = readByte();
        }
        return sb.toString();
    }
    private char[] ns(int n)
    {
        char[] buf = new char[n];
        int b = skip(), p = 0;
        while(p < n && !(isSpaceChar(b))){
            buf[p++] = (char)b;
            b = readByte();
        }
        return n == p ? buf : Arrays.copyOf(buf, p);
    }
    private char[][] nm(int n, int m)
    {
        char[][] map = new char[n][];
        for(int i = 0;i < n;i++)map[i] = ns(m);
        return map;
    }
    private int[] na(int n)
    {
        int[] a = new int[n];
        for(int i = 0;i < n;i++)a[i] = ni();
        return a;
    }
    private int ni()
    {
        int num = 0, b;
        boolean minus = false;
        while((b = readByte()) != -1 && !((b >= '0' && b <= '9') || b == '-'));
        if(b == '-'){
            minus = true;
            b = readByte();
        }
        while(true){
            if(b >= '0' && b <= '9'){
                num = num * 10 + (b - '0');
            }else{
                return minus ? -num : num;
            }
            b = readByte();
        }
    }
    private long nl()
    {
        long num = 0;
        int b;
        boolean minus = false;
        while((b = readByte()) != -1 && !((b >= '0' && b <= '9') || b == '-'));
        if(b == '-'){
            minus = true;
            b = readByte();
        }
        while(true){
            if(b >= '0' && b <= '9'){
                num = num * 10 + (b - '0');
            }else{
                return minus ? -num : num;
            }
            b = readByte();
        }
    }
    private static void tr(Object... o) { System.out.println(Arrays.deepToString(o)); }
}
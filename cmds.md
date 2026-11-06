2. 查询计算节点：

```bash
squeue -j "%USER" 
```

3. 在本机 PowerShell 建立隧道，把 `COMPUTE_HOST` 换成节点名：

```powershell
ssh -N -L 8006:gpu1-12:8006 hpc-hkustgz
```

保持这个窗口打开。


5. 运行完整音视频流式测试，建议戴耳机：

```powershell
python realtime_av_test.py --insecure
```

摄像头窗口按 `Q`，或终端按 `Ctrl+C` 退出。

如果只想先测试摄像头和文字输出：

```powershell
py realtime_av_test.py --insecure --no-mic --no-tts
```


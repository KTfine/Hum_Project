param(
    [string]$Voice = 'Microsoft Kangkang',
    [string]$OutputSubdir = '',
    [ValidateSet('baseline', 'generalization', 'all')][string]$Profile = 'all'
)
Add-Type -AssemblyName System.Speech
$probeRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'runtime_results'
if ($OutputSubdir) {
    $probeRoot = Join-Path $probeRoot $OutputSubdir
}
New-Item -ItemType Directory -Force -Path $probeRoot | Out-Null
$baseline = [ordered]@{
    'move_left_smile.wav' = '请把你自己向左移动一点，然后切换成微笑的表情。'
    'return_center.wav' = '现在请回到画面中间，恢复普通表情。'
    'visual_color_check.wav' = '请看真人摄像头主画面，左上角的方块是什么颜色？请用一句话回答。'
}
$generalization = [ordered]@{
    'right_surprised.wav' = '往右挪一点，换成惊讶的表情。'
    'half_size.wav' = '把你自己缩小到现在的一半。'
    'rotate_fifteen.wav' = '把你的旋转角度设置成十五度。'
    'quarter_happy.wav' = '移到画面横向四分之一的位置，表情改成开心。'
    'reset_all.wav' = '回到水平中间，恢复原始大小和零度，换回普通表情。'
    'do_nothing.wav' = '先不要移动，也不要换表情。'
}
$utterances = [ordered]@{}
if ($Profile -ne 'generalization') { foreach ($item in $baseline.GetEnumerator()) { $utterances[$item.Key] = $item.Value } }
if ($Profile -ne 'baseline') { foreach ($item in $generalization.GetEnumerator()) { $utterances[$item.Key] = $item.Value } }
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SelectVoice($Voice)
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    foreach ($item in $utterances.GetEnumerator()) {
        $synth.SetOutputToWaveFile((Join-Path $probeRoot $item.Key), $format)
        $synth.Speak($item.Value)
        $synth.SetOutputToNull()
    }
} finally {
    $synth.Dispose()
}
$utterances | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $probeRoot 'action-utterances.json') -Encoding utf8

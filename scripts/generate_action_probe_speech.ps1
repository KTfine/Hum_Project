param(
    [string]$Voice = 'Microsoft Kangkang',
    [string]$OutputSubdir = '',
    [ValidateSet('baseline', 'generalization', 'co-photo', 'all')][string]$Profile = 'all'
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
if ($Profile -in @('baseline', 'all')) { foreach ($item in $baseline.GetEnumerator()) { $utterances[$item.Key] = $item.Value } }
if ($Profile -in @('generalization', 'all')) { foreach ($item in $generalization.GetEnumerator()) { $utterances[$item.Key] = $item.Value } }
if ($Profile -eq 'co-photo') {
    $utterances['photo_not_yet.wav'] = '先不要合照，你留在小窗里就好。'
    $utterances['photo_enter.wav'] = '我们一起来拍照吧，请你进入画面和我合照。'
    $utterances['photo_move_left.wav'] = '现在请把你自己向画面的左边移动一点。'
    $utterances['photo_move_right.wav'] = '请你自己移动到画面右边四分之三的位置。'
    $utterances['photo_reenter.wav'] = '我们继续一起合照吧。'
    $utterances['photo_scale_denied.wav'] = '把你自己缩小一半。'
}
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

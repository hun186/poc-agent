# SRA-LogRotate.ps1
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$log = "D:\shared\TopicClassification\poc-agent\SRA-API_output.txt"
$max = 10MB

# 啟動時先砍舊檔（可視需要保留或註解掉）
if (Test-Path $log) {
    Remove-Item $log -Force
}

# 建立 UTF-8 寫入串流
$fs = New-Object System.IO.StreamWriter($log, $false, [System.Text.Encoding]::UTF8)
$fs.AutoFlush = $true

try {
    while ($true) {
        $line = [Console]::In.ReadLine()
        if ($null -eq $line) { break }

        # 超過容量就重建檔案
        if ((Test-Path $log) -and ((Get-Item $log).Length -gt $max)) {
            $fs.Flush()
            $fs.Close()
            Remove-Item $log -Force

            $fs = New-Object System.IO.StreamWriter($log, $false, [System.Text.Encoding]::UTF8)
            $fs.AutoFlush = $true
        }

        $fs.WriteLine($line)
    }
}
finally {
    $fs.Flush()
    $fs.Close()
}

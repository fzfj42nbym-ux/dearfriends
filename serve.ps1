# Локальный сервер для Dear Friends (без установки чего-либо).
# Запуск:  powershell -NoProfile -ExecutionPolicy Bypass -File serve.ps1
# Сайт:    http://127.0.0.1:8642
$root = $PSScriptRoot
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add('http://127.0.0.1:8642/')
$listener.Start()
Write-Output "serving $root on http://127.0.0.1:8642/"
while ($listener.IsListening) {
  try { $ctx = $listener.GetContext() } catch { break }
  $path = $ctx.Request.Url.AbsolutePath
  if ($path -eq '/') { $path = '/index.html' }
  $file = Join-Path $root ($path -replace '/', '\').TrimStart('\')
  if ((Test-Path $file -PathType Leaf) -and ($file.StartsWith($root))) {
    $bytes = [IO.File]::ReadAllBytes($file)
    $ext = [IO.Path]::GetExtension($file)
    $ctx.Response.ContentType = switch ($ext) {
      '.html' { 'text/html; charset=utf-8' }
      '.js'   { 'text/javascript' }
      '.css'  { 'text/css' }
      '.svg'  { 'image/svg+xml' }
      '.png'  { 'image/png' }
      default { 'application/octet-stream' }
    }
    $ctx.Response.ContentLength64 = $bytes.Length
    $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
  } else {
    $ctx.Response.StatusCode = 404
  }
  $ctx.Response.Close()
}

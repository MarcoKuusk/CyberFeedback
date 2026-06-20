$ErrorActionPreference = "Stop"

$secureKey = Read-Host "Paste your OpenAI API key" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)

try {
    $plainKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ([string]::IsNullOrWhiteSpace($plainKey)) {
        throw "OPENAI_API_KEY was empty."
    }

    [Environment]::SetEnvironmentVariable("OPENAI_API_KEY", $plainKey, "User")
    $env:OPENAI_API_KEY = $plainKey
    Write-Host "OPENAI_API_KEY saved to your Windows user environment."
    Write-Host "Restart your terminal before running the app in a new shell."
}
finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    Remove-Variable secureKey -ErrorAction SilentlyContinue
    Remove-Variable plainKey -ErrorAction SilentlyContinue
}

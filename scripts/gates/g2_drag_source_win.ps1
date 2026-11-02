# A window that offers one folder as a drag source, the way Explorer does.
#
# g2_os.drag moves the real pointer from it onto the app, so the drop arrives through OLE
# drag-and-drop as a user's would.
#
#   powershell -STA -File scripts/gates/g2_drag_source_win.ps1 <folder>
param([Parameter(Mandatory = $true)][string]$Folder)

Add-Type -AssemblyName System.Windows.Forms
$folderPath = (Resolve-Path $Folder).Path
$form = New-Object System.Windows.Forms.Form
$form.Text = 'G2 drag source'
$form.StartPosition = 'Manual'
$form.Location = New-Object System.Drawing.Point(40, 40)
$form.Size = New-Object System.Drawing.Size(260, 140)
$form.TopMost = $true
$label = New-Object System.Windows.Forms.Label
$label.Text = "Drag $(Split-Path $folderPath -Leaf)"
$label.Dock = 'Fill'
$label.TextAlign = 'MiddleCenter'
$label.Add_MouseDown({
    $data = New-Object System.Windows.Forms.DataObject
    $files = New-Object System.Collections.Specialized.StringCollection
    [void]$files.Add($folderPath)
    $data.SetFileDropList($files)
    [void]$label.DoDragDrop($data, [System.Windows.Forms.DragDropEffects]::Copy)
})
$form.Controls.Add($label)
[System.Windows.Forms.Application]::Run($form)

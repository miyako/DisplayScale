//%attributes = {"invisible":true}
var $ignored : Integer
var $parameter; $name; $target : Text
var $folderPath : Text
var $request; $result; $report : Object
var $payload; $monitor : Object
var $platform : Text
var $dpi : Real
var $tool : cs.DisplayScale.Display
var $requestFile; $statusFile : 4D.File
var $renamedExecutable : 4D.File
var $echoExecutable : 4D.File
var $cases : Collection
var $invalid : Variant
var HOST_StatusFile : 4D.File
var HOST_Phase : Text
var HOST_PreviousHandler : Text
$ignored:=Get database parameter(User param value; $parameter)
If (Is Windows)
	$requestFile:=File($parameter; fk platform path)
Else
	$requestFile:=File($parameter; fk posix path)
End if
$request:=JSON Parse($requestFile.getText())
If (Is Windows)
	$statusFile:=File($request.status; fk platform path)
Else
	$statusFile:=File($request.status; fk posix path)
End if
$statusFile.setText("{\"success\":false,\"phase\":\"starting\"}")
HOST_StatusFile:=$statusFile
HOST_Phase:="constructor"
HOST_PreviousHandler:=Method called on error(ek local)
ON ERR CALL("Host_error"; ek local)
$target:="macOS-universal"
If (Is Windows)
	$target:="Windows-x64"
End if
$tool:=cs.DisplayScale.Display.new($target)
$cases:=New collection("world"; "path with spaces"; "quote \" and \\ slash"; "line\nbreak"; "日本語"; "$() ; & % !")
$report:=New object("success"; True; "finished"; False; "cases"; New collection)
$report.compiled:=$tool._cli.compiled
HOST_Phase:="renamed executable"
If (Is Windows)
	$renamedExecutable:=File($request.executable; fk platform path)
Else
	$renamedExecutable:=File($request.executable; fk posix path)
End if
$report.renamedExecutable:=cs.DisplayScale._Process.new().execute($renamedExecutable; New collection("--version"))
If (Not($report.renamedExecutable.ok))
	$report.success:=False
End if
HOST_Phase:="feature cases"
If ($request.expectCompiled#$report.compiled)
	$report.success:=False
End if
$result:=$tool.monitors()
$report.monitors:=$result
$report.cases.push($result)
If (Not($result.ok))
	$report.success:=False
End if
$result:=$tool._cli.execute(New collection("monitors"; "unexpected"))
$report.invalid:=$result
If ($result.ok | ($result.exitCode#2))
	$report.success:=False
End if
$result:=$tool.version()
$report.version:=$result
If (Not($result.ok))
	$report.success:=False
Else
	If ($result.value.version#"0.1.3")
		$report.success:=False
	End if
End if
HOST_Phase:="missing executable"
$result:=cs.DisplayScale._CLI.new("missing-cli"; $target).execute(New collection("--version"))
$report.missing:=$result
If ($result.error.code#"missing_executable")
	$report.success:=False
End if
$result:=cs.DisplayScale.Display.new("unsupported-arm-target").version()
$report.unsupported:=$result
If ($result.error.code#"unsupported_architecture")
	$report.success:=False
End if
HOST_Phase:="launch failure"
$result:=cs.DisplayScale._Process.new().execute($requestFile; New collection)
$report.launch:=$result
If ($result.error.code#"launch_failed")
	$report.success:=False
End if
HOST_Phase:="malformed protocol"
$result:=$tool._decode(New object("ok"; True; "stdout"; "not json"+Char(10); "stderr"; ""; "exitCode"; 0); "monitors")
$report.protocol:=$result
If ($result.error.code#"invalid_protocol")
	$report.success:=False
End if
$report.protocolTypes:=New collection
For each ($name; New collection("{\"protocol\":true,\"monitors\":[]}"+Char(10); "{\"protocol\":false,\"monitors\":[]}"+Char(10)))
	$result:=$tool._decode(New object("ok"; True; "stdout"; $name; "stderr"; ""; "exitCode"; 0); "monitors")
	$report.protocolTypes.push($result)
	If ($result.ok | ($result.error.code#"invalid_protocol"))
		$report.success:=False
	End if
End for each
$result:=$tool._decode(New object("ok"; True; "stdout"; "{\"protocol\":null,\"monitors\":[]}"+Char(10); "stderr"; ""; "exitCode"; 0); "monitors")
$report.protocolNull:=$result
If ($result.ok | ($result.error.code#"invalid_protocol"))
	$report.success:=False
End if
$report.protocolScalars:=New collection
For each ($name; New collection("true"+Char(10); "false"+Char(10); "null"+Char(10); "1"+Char(10); "[]"+Char(10)))
	$result:=$tool._decode(New object("ok"; True; "stdout"; $name; "stderr"; ""; "exitCode"; 0); "monitors")
	$report.protocolScalars.push($result)
	If ($result.ok | ($result.error.code#"invalid_protocol"))
		$report.success:=False
	End if
End for each
HOST_Phase:="monitor decoder"
$report.decoderCases:=New collection
$report.fractionChecks:=True
For each ($dpi; New collection(120; 144; 121))
	$monitor:=New object("device"; "日本語 display"; "primary"; True; "bounds"; New object("left"; -1920; "top"; -100; "right"; 0; "bottom"; 980); "dpi"; $dpi; "scalePercent"; ($dpi/96)*100)
	$payload:=New object("protocol"; 2; "platform"; "windows"; "monitors"; New collection($monitor))
	$result:=$tool._decode(New object("ok"; True; "stdout"; JSON Stringify($payload)+Char(10); "stderr"; ""; "exitCode"; 0); "monitors")
	$report.decoderCases.push($result)
	If (Not($result.ok))
		$report.success:=False
		$report.fractionChecks:=False
	Else
		If (Abs($result.value.monitors[0].scalePercent-(($dpi/96)*100))>0.000000001)
			$report.success:=False
			$report.fractionChecks:=False
		End if
	End if
End for each
$report.invalidMonitors:=New collection
For each ($name; New collection("{\"protocol\":2,\"platform\":\"windows\",\"monitors\":null}"; "{\"protocol\":2,\"platform\":\"windows\",\"monitors\":[]}"; "{\"protocol\":2,\"platform\":\"windows\",\"monitors\":[null]}"; "{\"protocol\":2,\"platform\":\"windows\",\"monitors\":[1]}"; "{\"protocol\":2,\"platform\":\"windows\",\"monitors\":[{}]}"))
	$result:=$tool._decode(New object("ok"; True; "stdout"; $name+Char(10); "stderr"; ""; "exitCode"; 0); "monitors")
	$report.invalidMonitors.push($result)
	If ($result.ok | ($result.error.code#"invalid_protocol"))
		$report.success:=False
	End if
End for each
For each ($name; New collection("device"; "primary"; "bounds"; "dpi"; "scalePercent"))
	$monitor:=New object("device"; "display"; "primary"; True; "bounds"; New object("left"; 0; "top"; 0; "right"; 1920; "bottom"; 1080); "dpi"; 120; "scalePercent"; 125)
	$monitor[$name]:=Null
	$payload:=New object("protocol"; 2; "platform"; "windows"; "monitors"; New collection($monitor))
	$result:=$tool._decode(New object("ok"; True; "stdout"; JSON Stringify($payload)+Char(10); "stderr"; ""; "exitCode"; 0); "monitors")
	$report.invalidMonitors.push($result)
	If ($result.ok | ($result.error.code#"invalid_protocol"))
		$report.success:=False
	End if
End for each
For each ($name; New collection("wrongScale"; "noPrimary"; "invalidBounds"; "fractionalDpi"; "duplicateDevice"; "multipleLines"))
	$monitor:=New object("device"; "display"; "primary"; True; "bounds"; New object("left"; 0; "top"; 0; "right"; 1920; "bottom"; 1080); "dpi"; 120; "scalePercent"; 125)
	Case of
		: ($name="wrongScale")
			$monitor.scalePercent:=100
		: ($name="noPrimary")
			$monitor.primary:=False
		: ($name="invalidBounds")
			$monitor.bounds.right:=0
		: ($name="fractionalDpi")
			$monitor.dpi:=120.5
	End case
	$payload:=New object("protocol"; 2; "platform"; "windows"; "monitors"; New collection($monitor))
	If ($name="duplicateDevice")
		$payload.monitors.push($monitor)
	End if
	$parameter:=JSON Stringify($payload)+Char(10)
	If ($name="multipleLines")
		$parameter+=Char(10)
	End if
	$result:=$tool._decode(New object("ok"; True; "stdout"; $parameter; "stderr"; ""; "exitCode"; 0); "monitors")
	$report.invalidMonitors.push($result)
	If ($result.ok | ($result.error.code#"invalid_protocol"))
		$report.success:=False
	End if
End for each
HOST_Phase:="macOS monitor decoder"
$report.macDecoderCases:=New collection
For each ($name; New collection("retina"; "moreSpace"; "external"))
	Case of
		: ($name="retina")
			$monitor:=New object("device"; "display-1"; "primary"; True; "bounds"; New object("left"; 0; "top"; 0; "right"; 1512; "bottom"; 982); "backingPixels"; New object("width"; 3024; "height"; 1964); "nativePixels"; New object("width"; 3024; "height"; 1964); "backingScalePercent"; 200; "scalePercent"; 200)
		: ($name="moreSpace")
			$monitor:=New object("device"; "display-1"; "primary"; True; "bounds"; New object("left"; 0; "top"; 0; "right"; 1800; "bottom"; 1169); "backingPixels"; New object("width"; 3600; "height"; 2338); "nativePixels"; New object("width"; 3024; "height"; 1964); "backingScalePercent"; 200; "scalePercent"; 168)
		Else
			$monitor:=New object("device"; "display-2"; "primary"; True; "bounds"; New object("left"; 0; "top"; 0; "right"; 2560; "bottom"; 1440); "backingPixels"; New object("width"; 2560; "height"; 1440); "nativePixels"; New object("width"; 2560; "height"; 1440); "backingScalePercent"; 100; "scalePercent"; 100)
	End case
	$payload:=New object("protocol"; 2; "platform"; "macos"; "monitors"; New collection($monitor))
	$result:=$tool._decode(New object("ok"; True; "stdout"; JSON Stringify($payload)+Char(10); "stderr"; ""; "exitCode"; 0); "monitors")
	$report.macDecoderCases.push($result)
	If (Not($result.ok))
		$report.success:=False
	End if
End for each
$report.invalidMacMonitors:=New collection
For each ($name; New collection("device"; "primary"; "bounds"; "backingPixels"; "nativePixels"; "backingScalePercent"; "scalePercent"; "wrongScale"; "wrongBackingScale"; "zeroNative"; "fractionalPixel"; "unknownPlatform"))
	$monitor:=New object("device"; "display-1"; "primary"; True; "bounds"; New object("left"; 0; "top"; 0; "right"; 1512; "bottom"; 982); "backingPixels"; New object("width"; 3024; "height"; 1964); "nativePixels"; New object("width"; 3024; "height"; 1964); "backingScalePercent"; 200; "scalePercent"; 200)
	$platform:="macos"
	Case of
		: ($name="wrongScale")
			$monitor.scalePercent:=100
		: ($name="wrongBackingScale")
			$monitor.backingScalePercent:=100
		: ($name="zeroNative")
			$monitor.nativePixels.width:=0
		: ($name="fractionalPixel")
			$monitor.backingPixels.width:=3024.5
		: ($name="unknownPlatform")
			$platform:="linux"
		Else
			$monitor[$name]:=Null
	End case
	$payload:=New object("protocol"; 2; "platform"; $platform; "monitors"; New collection($monitor))
	$result:=$tool._decode(New object("ok"; True; "stdout"; JSON Stringify($payload)+Char(10); "stderr"; ""; "exitCode"; 0); "monitors")
	$report.invalidMacMonitors.push($result)
	If ($result.ok | ($result.error.code#"invalid_protocol"))
		$report.success:=False
	End if
End for each
$parameter:=$requestFile.path
If (Is Windows)
	$parameter:=$requestFile.platformPath
End if
HOST_Phase:="File argument"
If (Is Windows)
	$echoExecutable:=File($request.echo; fk platform path)
Else
	$echoExecutable:=File($request.echo; fk posix path)
End if
$report.pathChecks:=True
$report.quotedArguments:=New collection
For each ($name; $cases)
	$result:=cs.DisplayScale._Process.new().execute($echoExecutable; New collection($name))
	$report.quotedArguments.push($result)
	If (Not($result.ok))
		$report.success:=False
	Else
		If (JSON Parse($result.stdout).arguments[0]#$name)
			$report.success:=False
			$report.pathChecks:=False
		End if
	End if
End for each
$result:=cs.DisplayScale._Process.new().execute($echoExecutable; New collection($requestFile))
$report.fileArgument:=$result
If (Not($result.ok))
	$report.success:=False
Else
	If (JSON Parse($result.stdout).arguments[0]#$parameter)
		$report.success:=False
		$report.pathChecks:=False
	End if
End if
$report.rejectedArguments:=New collection
HOST_Phase:="scalar arguments"
For each ($invalid; New collection(123; 1.25; True; False; Null; Current date; Current time; New collection; New object))
	$result:=cs.DisplayScale._Process.new().execute($requestFile; New collection($invalid))
	$report.rejectedArguments.push(New object("type"; Value type($invalid); "result"; $result))
	If ($result.ok | ($result.error.code#"invalid_argument"))
		$report.success:=False
	End if
End for each
$report.rejectedNul:=New collection
HOST_Phase:="NUL arguments"
For each ($name; New collection(Char(0)+"prefix"; "middle"+Char(0)+"suffix"; "trailing"+Char(0)))
	$result:=cs.DisplayScale._Process.new().execute($requestFile; New collection($name))
	$report.rejectedNul.push($result)
	If ($result.ok | ($result.error.code#"invalid_argument"))
		$report.success:=False
	End if
End for each
$report.missingFile:=cs.DisplayScale._Process.new().execute(Null; New collection)
$report.missingArguments:=cs.DisplayScale._Process.new().execute($requestFile; Null)
If ($report.missingFile.ok | ($report.missingFile.error.code#"invalid_argument"))
	$report.success:=False
End if
If ($report.missingArguments.ok | ($report.missingArguments.error.code#"invalid_argument"))
	$report.success:=False
End if
HOST_Phase:="Folder argument"
$result:=cs.DisplayScale._Process.new().execute($echoExecutable; New collection($requestFile.parent))
$report.folderArgument:=$result
$folderPath:=$requestFile.parent.path
If (Is Windows)
	$folderPath:=$requestFile.parent.platformPath
End if
If (Not($result.ok))
	$report.success:=False
Else
	If (JSON Parse($result.stdout).arguments[0]#$folderPath)
		$report.success:=False
		$report.pathChecks:=False
	End if
End if
$report.finished:=True
ON ERR CALL(HOST_PreviousHandler; ek local)
$statusFile.setText(JSON Stringify($report))
HOST_StatusFile:=Null
HOST_Phase:=""
HOST_PreviousHandler:=""
QUIT 4D

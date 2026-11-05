//%attributes = {"invisible":true}
var $ignored : Integer
var $parameter : Text
var $request; $status; $options : Object
var $project; $output : 4D.File
$ignored:=Get database parameter(User param value; $parameter)
If (Is Windows)
	$request:=JSON Parse(File($parameter; fk platform path).getText())
	$project:=File($request.project; fk platform path)
	$output:=File($request.status; fk platform path)
Else 
	$request:=JSON Parse(File($parameter; fk posix path).getText())
	$project:=File($request.project; fk posix path)
	$output:=File($request.status; fk posix path)
End if 
$options:=New object("targets"; $request.targets; "generateSymbols"; False; "generateSyntaxFile"; True)
$status:=Compile project($project; $options)
If (Is Windows)
	$status.project:=$project.platformPath
Else 
	$status.project:=$project.path
End if 
$status.targets:=$options.targets
$output.setText(JSON Stringify($status))
QUIT 4D

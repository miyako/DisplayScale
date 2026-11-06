//%attributes = {"invisible":true}
#DECLARE($action : Text)->$errors : Collection
var CLI_LastErrors : Collection
Case of 
	: ($action="reset")
		CLI_LastErrors:=Null
	: ($action="take")
		$errors:=CLI_LastErrors
		CLI_LastErrors:=Null
	Else 
		CLI_LastErrors:=Last errors
End case 

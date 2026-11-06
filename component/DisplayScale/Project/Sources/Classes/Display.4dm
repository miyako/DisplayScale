property _cli : cs._CLI

Class constructor($target : Text)
	This._cli:=cs._CLI.new("display-scale"; $target)

Function monitors()->$result : Object
	$result:=This._decode(This._cli.execute(New collection("monitors")); "monitors")

Function version()->$result : Object
	$result:=This._decode(This._cli.execute(New collection("--version")); "version")

Function _decode($result : Object; $field : Text)->$decoded : Object
	var $payload : Variant
	var $previous : Text
	var $parseErrors : Collection
	var $bounds : Object
	var $monitor : Variant
	var $devices : Collection
	var $coordinate : Variant
	var $primaryCount : Integer
	var $fieldName : Text
	var $size : Variant
	var $platform : Text
	var $pointWidth : Real
	var $dimension : Text
	If (Not($result.ok))
		return $result
	End if
	If (Value type($result.stdout)#Is text)
		return This._invalid($result; "CLI stdout must be Text")
	End if
	If ((Position(Char(10); $result.stdout; *)#Length($result.stdout)) | (Position(Char(13); $result.stdout; *)>0))
		return This._invalid($result; "CLI response must be exactly one JSON line with LF")
	End if
	$previous:=Method called on error(ek local)
	_CaptureError("reset")
	ON ERR CALL("_CaptureError"; ek local)
	$payload:=JSON Parse($result.stdout)
	ON ERR CALL($previous; ek local)
	$parseErrors:=_CaptureError("take")
	If (($parseErrors#Null) | (Value type($payload)#Is object))
		$result.ok:=False
		$result.error:=New object("code"; "invalid_protocol"; "message"; "CLI response must be a JSON object"; "details"; $parseErrors)
		return $result
	End if
	If ((Value type($payload.protocol)#Is real) & (Value type($payload.protocol)#Is longint))
		$result.ok:=False
		$result.error:=New object("code"; "invalid_protocol"; "message"; "Unsupported CLI protocol version")
		return $result
	End if
	If ($payload.protocol#2)
		$result.ok:=False
		$result.error:=New object("code"; "invalid_protocol"; "message"; "Unsupported CLI protocol version")
		return $result
	End if
	Case of
		: ($field="version")
			If (Value type($payload.version)#Is text)
				return This._invalid($result; "CLI version must be Text")
			End if
			If ($payload.version#"0.1.3")
				return This._invalid($result; "CLI version does not match component")
			End if
		: ($field="monitors")
			If (Value type($payload.platform)#Is text)
				return This._invalid($result; "CLI platform must be Text")
			End if
			If (($payload.platform#"windows") & ($payload.platform#"macos"))
				return This._invalid($result; "CLI platform must be windows or macos")
			End if
			$platform:=$payload.platform
			If (Value type($payload.monitors)#Is collection)
				return This._invalid($result; "CLI monitors must be a Collection")
			End if
			If ($payload.monitors.length=0)
				return This._invalid($result; "CLI monitors must not be empty")
			End if
			$devices:=New collection
			$primaryCount:=0
			For each ($monitor; $payload.monitors)
				If (Value type($monitor)#Is object)
					return This._invalid($result; "Monitor must be an Object")
				End if
				If (Value type($monitor.device)#Is text)
					return This._invalid($result; "Monitor device must be Text")
				End if
				If (($monitor.device="") | (Position(Char(0); $monitor.device; *)>0))
					return This._invalid($result; "Monitor device must be nonempty without NUL")
				End if
				If ($devices.indexOf($monitor.device)>=0)
					return This._invalid($result; "Monitor devices must be unique")
				End if
				$devices.push($monitor.device)
				If (Value type($monitor.primary)#Is boolean)
					return This._invalid($result; "Monitor primary must be Boolean")
				End if
				If ($monitor.primary)
					$primaryCount+=1
					If ($devices.length#1)
						return This._invalid($result; "Primary monitor must be first")
					End if
				End if
				If (Value type($monitor.bounds)#Is object)
					return This._invalid($result; "Monitor bounds must be an Object")
				End if
				$bounds:=$monitor.bounds
				For each ($fieldName; New collection("left"; "top"; "right"; "bottom"))
					$coordinate:=$bounds[$fieldName]
					If ((Value type($coordinate)#Is real) & (Value type($coordinate)#Is longint))
						return This._invalid($result; "Monitor bounds must contain integer coordinates")
					End if
					If (($coordinate#Int($coordinate)) | ($coordinate<(-2147483648.0)) | ($coordinate>2147483647.0))
						return This._invalid($result; "Monitor coordinate is outside signed 32-bit range")
					End if
				End for each
				If (($bounds.right<=$bounds.left) | ($bounds.bottom<=$bounds.top))
					return This._invalid($result; "Monitor bounds must have positive area")
				End if
				If ($platform="windows")
					If ((Value type($monitor.dpi)#Is real) & (Value type($monitor.dpi)#Is longint))
						return This._invalid($result; "Monitor dpi must be numeric")
					End if
					If (($monitor.dpi<=0) | ($monitor.dpi#Int($monitor.dpi)) | ($monitor.dpi>4294967295.0))
						return This._invalid($result; "Monitor dpi must be a positive UINT")
					End if
					If ((Value type($monitor.scalePercent)#Is real) & (Value type($monitor.scalePercent)#Is longint))
						return This._invalid($result; "Monitor scalePercent must be numeric")
					End if
					If (Abs($monitor.scalePercent-(($monitor.dpi/96)*100))>0.000000001)
						return This._invalid($result; "Monitor scalePercent does not match effective dpi")
					End if
				Else
					$pointWidth:=$bounds.right-$bounds.left
					For each ($fieldName; New collection("backingPixels"; "nativePixels"))
						$size:=$monitor[$fieldName]
						If (Value type($size)#Is object)
							return This._invalid($result; "Monitor pixel size must be an Object")
						End if
						For each ($dimension; New collection("width"; "height"))
							$coordinate:=$size[$dimension]
							If ((Value type($coordinate)#Is real) & (Value type($coordinate)#Is longint))
								return This._invalid($result; "Monitor pixel size must be numeric")
							End if
							If (($coordinate<=0) | ($coordinate#Int($coordinate)) | ($coordinate>4294967295.0))
								return This._invalid($result; "Monitor pixel size must be a positive UINT")
							End if
						End for each
					End for each
					If ((Value type($monitor.backingScalePercent)#Is real) & (Value type($monitor.backingScalePercent)#Is longint))
						return This._invalid($result; "Monitor backingScalePercent must be numeric")
					End if
					If (Abs($monitor.backingScalePercent-(($monitor.backingPixels.width/$pointWidth)*100))>0.000000001)
						return This._invalid($result; "Monitor backingScalePercent does not match backing pixels")
					End if
					If ((Value type($monitor.scalePercent)#Is real) & (Value type($monitor.scalePercent)#Is longint))
						return This._invalid($result; "Monitor scalePercent must be numeric")
					End if
					If (Abs($monitor.scalePercent-(($monitor.nativePixels.width/$pointWidth)*100))>0.000000001)
						return This._invalid($result; "Monitor scalePercent does not match native pixels")
					End if
				End if
			End for each
			If ($primaryCount#1)
				return This._invalid($result; "Exactly one primary monitor is required")
			End if
		Else
			return This._invalid($result; "Unknown response schema")
	End case
	$result.value:=$payload
	$decoded:=$result

Function _invalid($result : Object; $message : Text)->$invalid : Object
	$result.ok:=False
	$result.error:=New object("code"; "invalid_protocol"; "message"; $message)
	$invalid:=$result

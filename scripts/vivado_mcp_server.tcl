## vivado-mcp TCP bridge for Vivado GUI.
##
## Security hardening:
## - binds to 127.0.0.1 only
## - requires a VMCP_AUTH token on every request

namespace eval ::vmcp {
    variable DEFAULT_PORT 9999
    variable POOL_SIZE 5
    variable active_port 0
    variable server_sock {}
    variable captured_buf ""
    variable required_token ""
}

proc ::vmcp::json_escape {s} {
    set result [string map [list \
        "\\" "\\\\" \
        "\"" "\\\"" \
        "\n" "\\n" \
        "\r" "\\r" \
        "\t" "\\t" \
        "\b" "\\b" \
        "\f" "\\f" \
    ] $s]
    return $result
}

proc ::vmcp::send_response {chan rc output} {
    set escaped [::vmcp::json_escape $output]
    set json "\{\"rc\":$rc,\"output\":\"$escaped\"\}"
    set bytes [encoding convertto utf-8 $json]
    set len [string length $bytes]
    puts -nonewline $chan [binary format I $len]
    puts -nonewline $chan $bytes
    flush $chan
}

proc ::vmcp::read_request {chan} {
    set hdr [read $chan 4]
    if {[string length $hdr] != 4} {
        return ""
    }
    binary scan $hdr I len
    if {$len <= 0 || $len > 10485760} {
        return ""
    }
    set payload_bytes [read $chan $len]
    if {[string length $payload_bytes] != $len} {
        return ""
    }
    return [encoding convertfrom utf-8 $payload_bytes]
}

proc ::vmcp::captured_puts {args} {
    set nonewline 0
    set idx 0
    if {[lindex $args $idx] eq "-nonewline"} {
        set nonewline 1
        incr idx
    }
    set remaining [lrange $args $idx end]
    set chan "stdout"
    set text ""
    if {[llength $remaining] >= 2} {
        set chan [lindex $remaining 0]
        set text [lindex $remaining 1]
    } elseif {[llength $remaining] == 1} {
        set text [lindex $remaining 0]
    }

    if {$chan ne "stdout"} {
        catch {eval ::__orig_puts $args}
        return
    }

    append ::vmcp::captured_buf $text
    if {!$nonewline} {
        append ::vmcp::captured_buf "\n"
    }
    return ""
}

proc ::vmcp::exec_with_capture {cmd} {
    set ::vmcp::captured_buf ""
    rename ::puts ::__orig_puts
    rename ::vmcp::captured_puts ::puts

    set rc [catch {uplevel #0 $cmd} ret __opts]

    rename ::puts ::vmcp::captured_puts
    rename ::__orig_puts ::puts

    set merged $::vmcp::captured_buf
    if {$ret ne ""} {
        if {$merged ne "" && [string index $merged end] ne "\n"} {
            append merged "\n"
        }
        append merged $ret
    }
    return [list $rc $merged]
}

proc ::vmcp::decode_request {payload} {
    variable required_token

    set newline_idx [string first "\n" $payload]
    if {$newline_idx < 0} {
        return [list 0 "Missing auth header"]
    }

    set header [string range $payload 0 [expr {$newline_idx - 1}]]
    set body [string range $payload [expr {$newline_idx + 1}] end]

    if {![regexp {^VMCP_AUTH (.+)$} $header -> presented_token]} {
        return [list 0 "Malformed auth header"]
    }
    if {$required_token eq ""} {
        return [list 0 "Server token is not configured"]
    }
    if {$presented_token ne $required_token} {
        return [list 0 "Authentication failed"]
    }

    return [list 1 $body]
}

proc ::vmcp::on_readable {chan} {
    if {[eof $chan] || [catch {fblocked $chan} blocked]} {
        catch {close $chan}
        return
    }

    set payload [::vmcp::read_request $chan]
    if {$payload eq ""} {
        catch {close $chan}
        return
    }

    set decoded [::vmcp::decode_request $payload]
    set ok [lindex $decoded 0]
    set data [lindex $decoded 1]
    if {!$ok} {
        catch {::vmcp::send_response $chan 1 $data}
        catch {close $chan}
        return
    }

    set result [::vmcp::exec_with_capture $data]
    set rc [lindex $result 0]
    set output [lindex $result 1]
    if {[catch {::vmcp::send_response $chan $rc $output} err]} {
        catch {close $chan}
    }
}

proc ::vmcp::on_accept {chan addr port} {
    fconfigure $chan -translation binary -buffering none -blocking 1
    fileevent $chan readable [list ::vmcp::on_readable $chan]
}

proc ::vmcp::start {} {
    variable DEFAULT_PORT
    variable POOL_SIZE
    variable active_port
    variable server_sock
    variable required_token

    set pref $DEFAULT_PORT
    if {[info exists ::VMCP_PORT_PREF]} {
        set pref $::VMCP_PORT_PREF
    }
    if {[info exists ::VMCP_AUTH_TOKEN]} {
        set required_token $::VMCP_AUTH_TOKEN
    }
    set port_max [expr {$pref + $POOL_SIZE - 1}]

    for {set p $pref} {$p <= $port_max} {incr p} {
        if {[catch {socket -server ::vmcp::on_accept -myaddr 127.0.0.1 $p} sock] == 0} {
            set server_sock $sock
            set active_port $p
            puts "vivado-mcp server ready on 127.0.0.1:$p"
            return $p
        }
    }
    return 0
}

::vmcp::start

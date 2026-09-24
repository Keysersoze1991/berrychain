import 'dart:convert';
import 'dart:typed_data';

/// Byte-for-byte the reference implementation's
/// `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`.
/// Every hash, txid and signature on the chain is over this encoding, so the
/// phone must produce exactly the same bytes as a node.
String canonicalJson(Object? value) {
  final sb = StringBuffer();
  _write(value, sb);
  return sb.toString();
}

Uint8List canonicalBytes(Object? value) =>
    Uint8List.fromList(ascii.encode(canonicalJson(value)));

void _write(Object? v, StringBuffer sb) {
  if (v == null) {
    sb.write('null');
  } else if (v is bool) {
    sb.write(v ? 'true' : 'false');
  } else if (v is int) {
    sb.write(v.toString());
  } else if (v is BigInt) {
    sb.write(v.toString());
  } else if (v is double) {
    throw ArgumentError('floating point values never appear in chain data');
  } else if (v is String) {
    _writeString(v, sb);
  } else if (v is List) {
    sb.write('[');
    for (var i = 0; i < v.length; i++) {
      if (i > 0) sb.write(',');
      _write(v[i], sb);
    }
    sb.write(']');
  } else if (v is Map) {
    final keys = v.keys.map((k) => k as String).toList()..sort(_byCodePoint);
    sb.write('{');
    for (var i = 0; i < keys.length; i++) {
      if (i > 0) sb.write(',');
      _writeString(keys[i], sb);
      sb.write(':');
      _write(v[keys[i]], sb);
    }
    sb.write('}');
  } else {
    throw ArgumentError('cannot encode ${v.runtimeType}');
  }
}

/// Python orders keys by Unicode code point.
int _byCodePoint(String a, String b) {
  final ra = a.runes.toList(), rb = b.runes.toList();
  for (var i = 0; i < ra.length && i < rb.length; i++) {
    if (ra[i] != rb[i]) return ra[i] - rb[i];
  }
  return ra.length - rb.length;
}

const _hex = '0123456789abcdef';

/// ensure_ascii=True: everything outside printable ASCII becomes \uXXXX, one
/// escape per UTF-16 code unit (so astral characters become surrogate pairs),
/// lowercase hex, and the short escapes for the usual control characters.
void _writeString(String s, StringBuffer sb) {
  sb.write('"');
  for (final u in s.codeUnits) {
    switch (u) {
      case 0x22:
        sb.write(r'\"');
      case 0x5c:
        sb.write(r'\\');
      case 0x0a:
        sb.write(r'\n');
      case 0x0d:
        sb.write(r'\r');
      case 0x09:
        sb.write(r'\t');
      case 0x08:
        sb.write(r'\b');
      case 0x0c:
        sb.write(r'\f');
      default:
        if (u >= 0x20 && u <= 0x7e) {
          sb.writeCharCode(u);
        } else {
          sb.write(r'\u');
          sb.write(_hex[(u >> 12) & 0xf]);
          sb.write(_hex[(u >> 8) & 0xf]);
          sb.write(_hex[(u >> 4) & 0xf]);
          sb.write(_hex[u & 0xf]);
        }
    }
  }
  sb.write('"');
}

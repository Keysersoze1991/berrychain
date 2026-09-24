/// 1 BERRY = 100,000,000 seeds. Amounts on the wire are integer seeds.
const seedsPerBerry = 100000000;
const minFee = 10000;

String formatBerry(int seeds, {bool trim = true}) {
  final neg = seeds < 0;
  final s = seeds.abs();
  final whole = s ~/ seedsPerBerry;
  var frac = (s % seedsPerBerry).toString().padLeft(8, '0');
  if (trim) {
    frac = frac.replaceFirst(RegExp(r'0+$'), '');
  }
  final w = _group(whole);
  return '${neg ? '-' : ''}$w${frac.isEmpty ? '' : '.$frac'}';
}

String _group(int n) {
  final s = n.toString();
  final sb = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) sb.write(',');
    sb.write(s[i]);
  }
  return sb.toString();
}

/// Parse a decimal BERRY string ("0.25", "1,000") into seeds. Throws on more
/// than eight decimals or a negative amount.
int parseBerry(String text) {
  final t = text.replaceAll(',', '').trim();
  if (t.isEmpty || t.startsWith('-')) throw const FormatException('enter an amount');
  final parts = t.split('.');
  if (parts.length > 2) throw const FormatException('not a number');
  final whole = parts[0].isEmpty ? 0 : int.parse(parts[0]);
  var frac = parts.length == 2 ? parts[1] : '';
  if (frac.length > 8) throw const FormatException('at most eight decimals');
  frac = frac.padRight(8, '0');
  return whole * seedsPerBerry + (frac.isEmpty ? 0 : int.parse(frac));
}

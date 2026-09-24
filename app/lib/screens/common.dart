import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../main.dart';

String shortAddress(String a) => a.length > 16 ? '${a.substring(0, 10)}…${a.substring(a.length - 6)}' : a;

void toast(BuildContext context, String msg) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
}

Future<void> copyToClipboard(BuildContext context, String text, {String what = 'Copied'}) async {
  await Clipboard.setData(ClipboardData(text: text));
  if (context.mounted) toast(context, what);
}

/// A gold-topped card, like the site's tiles.
class Tile extends StatelessWidget {
  final String label;
  final Widget child;
  final Widget? trailing;
  const Tile({super.key, required this.label, required this.child, this.trailing});
  @override
  Widget build(BuildContext context) => Card(
        shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.all(Radius.circular(12)),
          side: BorderSide(color: Color(0xFFDCCFB4)),
        ),
        child: Container(
          decoration: const BoxDecoration(border: Border(top: BorderSide(color: Palette.gold, width: 3)), borderRadius: BorderRadius.vertical(top: Radius.circular(12))),
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 14),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label.toUpperCase(), style: const TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883))),
                    const SizedBox(height: 6),
                    child,
                  ],
                ),
              ),
              if (trailing != null) trailing!,
            ],
          ),
        ),
      );
}

/// A passphrase field with the show/hide eye.
class PassphraseField extends StatefulWidget {
  final TextEditingController controller;
  final String label;
  final void Function(String)? onSubmitted;
  const PassphraseField({super.key, required this.controller, this.label = 'Passphrase', this.onSubmitted});
  @override
  State<PassphraseField> createState() => _PassphraseFieldState();
}

class _PassphraseFieldState extends State<PassphraseField> {
  bool hidden = true;
  @override
  Widget build(BuildContext context) => TextField(
        controller: widget.controller,
        obscureText: hidden,
        autocorrect: false,
        enableSuggestions: false,
        onSubmitted: widget.onSubmitted,
        decoration: InputDecoration(
          labelText: widget.label,
          suffixIcon: IconButton(icon: Icon(hidden ? Icons.visibility : Icons.visibility_off), onPressed: () => setState(() => hidden = !hidden)),
        ),
      );
}

/// Runs [action] with a blocking progress dialog; shows errors as a toast.
Future<T?> runBusy<T>(BuildContext context, String message, Future<T> Function() action) async {
  showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => AlertDialog(content: Row(children: [const CircularProgressIndicator(), const SizedBox(width: 20), Expanded(child: Text(message))])),
  );
  try {
    final r = await action();
    if (context.mounted) Navigator.of(context, rootNavigator: true).pop();
    return r;
  } catch (e) {
    if (context.mounted) {
      Navigator.of(context, rootNavigator: true).pop();
      toast(context, '$e'.replaceFirst(RegExp(r'^\w+Error: '), '').replaceFirst('Invalid argument(s): ', ''));
    }
    return null;
  }
}

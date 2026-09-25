import 'package:flutter/material.dart';

import '../main.dart';
import '../session.dart';
import 'common.dart';
import 'letters.dart';

/// Everyone you have written to or heard from. Tap to write, hold to name.
class ContactsScreen extends StatelessWidget {
  const ContactsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('People')),
      body: ListenableBuilder(
        listenable: s,
        builder: (context, _) => RefreshIndicator(
          onRefresh: s.refresh,
          child: ListView(
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 12, 16, 4),
                child: Text('Everyone you have corresponded with, newest first. Tap to write; hold to give them a name that stays on this phone.', style: TextStyle(color: Color(0xFF6F7883), fontSize: 13)),
              ),
              for (final c in s.contacts) ContactRow(c),
              if (s.contacts.isEmpty) const Padding(padding: EdgeInsets.all(32), child: Text('Nobody yet.', textAlign: TextAlign.center)),
            ],
          ),
        ),
      ),
    );
  }
}

class ContactRow extends StatelessWidget {
  final Contact c;
  final void Function(Contact)? onPick;
  const ContactRow(this.c, {super.key, this.onPick});

  Future<void> rename(BuildContext context) async {
    final s = SessionScope.of(context);
    final ctl = TextEditingController(text: c.nickname);
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Name this person'),
        content: TextField(controller: ctl, autofocus: true, decoration: InputDecoration(hintText: c.name.isNotEmpty ? c.name : 'e.g. Mum', helperText: 'Kept on this phone only')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Save')),
        ],
      ),
    );
    if (ok == true) await s.setNickname(c.address, ctl.text);
  }

  @override
  Widget build(BuildContext context) {
    final isHm = c.address == Network.harbourmaster;
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: isHm ? Palette.gold : const Color(0xFFDCCFB4),
        foregroundColor: Palette.sea,
        child: Icon(isHm ? Icons.anchor : Icons.person_outline, size: 20),
      ),
      title: Text(c.label),
      subtitle: Text('${shortAddress(c.address)}${c.name.isNotEmpty && c.nickname.isNotEmpty ? ' · ${c.name}' : ''}${c.letters > 0 ? ' · ${c.letters} letter${c.letters == 1 ? '' : 's'}' : (isHm ? ' · answers every letter' : '')}',
          style: const TextStyle(fontSize: 12.5)),
      trailing: const Icon(Icons.edit_outlined, size: 18, color: Color(0xFF9A8D94)),
      onTap: () {
        if (onPick != null) return onPick!(c);
        Navigator.push(context, MaterialPageRoute(builder: (_) => ComposeScreen(to: c.address)));
      },
      onLongPress: () => rename(context),
    );
  }
}

/// A picker for the compose screen: returns the chosen contact, or null.
Future<Contact?> pickContact(BuildContext context) {
  final s = SessionScope.of(context);
  return showModalBottomSheet<Contact>(
    context: context,
    showDragHandle: true,
    builder: (ctx) => SessionScope(
      session: s,
      child: ListView(
        shrinkWrap: true,
        children: [
          const Padding(padding: EdgeInsets.fromLTRB(20, 0, 20, 8), child: Text('Write to', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 16))),
          for (final c in s.contacts) ContactRow(c, onPick: (picked) => Navigator.pop(ctx, picked)),
          const SizedBox(height: 12),
        ],
      ),
    ),
  );
}

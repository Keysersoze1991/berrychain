import 'package:flutter/material.dart';

import '../core/letters.dart';
import '../core/crypto.dart';
import '../main.dart';
import '../session.dart';
import 'common.dart';
import 'letters.dart';

/// Everyone you have written to or heard from, and the crews you write to
/// at once. Tap to write, hold to name (or, for a crew, to disband).
class ContactsScreen extends StatelessWidget {
  const ContactsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Contacts'),
        actions: [IconButton(icon: const Icon(Icons.group_add_outlined), tooltip: 'New crew', onPressed: () => editGroup(context))],
      ),
      body: ListenableBuilder(
        listenable: s,
        builder: (context, _) => RefreshIndicator(
          onRefresh: s.refresh,
          child: ListView(
            children: [
              if (s.groups.isNotEmpty) ...[
                const Padding(padding: EdgeInsets.fromLTRB(16, 12, 16, 4), child: Text('CREWS', style: TextStyle(fontSize: 11.5, letterSpacing: 1.2, fontWeight: FontWeight.w600, color: Color(0xFF6F7883)))),
                for (final g in s.groups) GroupRow(g),
                const Divider(height: 20),
              ],
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                child: Text(
                  s.groups.isEmpty
                      ? 'Everyone you have corresponded with, newest first. Tap to write; hold to give them a name that stays on this phone. The crew button above makes a set of contacts you can write to at once.'
                      : 'Everyone you have corresponded with, newest first. Tap to write; hold to name.',
                  style: const TextStyle(color: Color(0xFF6F7883), fontSize: 13),
                ),
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

class GroupRow extends StatelessWidget {
  final LetterGroup g;
  final void Function(LetterGroup)? onPick;
  const GroupRow(this.g, {super.key, this.onPick});

  @override
  Widget build(BuildContext context) {
    final s = SessionScope.of(context);
    final names = g.members.map((m) => s.contacts.where((c) => c.address == m).map((c) => c.label).firstOrNull ?? shortAddress(m)).join(', ');
    return ListTile(
      leading: const CircleAvatar(backgroundColor: Color(0xFFDCCFB4), foregroundColor: Palette.sea, child: Icon(Icons.groups_outlined, size: 20)),
      title: Text(g.name),
      subtitle: Text('${g.members.length} people · $names', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12.5)),
      trailing: const Icon(Icons.edit_outlined, size: 18, color: Color(0xFF9A8D94)),
      onTap: () {
        if (onPick != null) return onPick!(g);
        Navigator.push(context, MaterialPageRoute(builder: (_) => ComposeScreen(group: g)));
      },
      onLongPress: () => editGroup(context, existing: g),
    );
  }
}

/// Make or change a group: a name, ticks against your people, and a box for
/// addresses you have not written to yet.
Future<void> editGroup(BuildContext context, {LetterGroup? existing}) async {
  final s = SessionScope.of(context);
  final name = TextEditingController(text: existing?.name ?? '');
  final extra = TextEditingController();
  final chosen = <String>{...?existing?.members};
  final result = await showDialog<String>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setState) => AlertDialog(
        title: Text(existing == null ? 'New crew' : 'Edit crew'),
        content: SizedBox(
          width: 420,
          child: ListView(
            shrinkWrap: true,
            children: [
              TextField(controller: name, autofocus: existing == null, decoration: const InputDecoration(labelText: 'Crew name', helperText: 'Travels inside each letter, sealed; never on the chain')),
              const SizedBox(height: 10),
              for (final c in s.contacts)
                CheckboxListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: Text(c.label),
                  subtitle: Text(shortAddress(c.address), style: const TextStyle(fontSize: 11.5, fontFamily: 'monospace')),
                  value: chosen.contains(c.address),
                  onChanged: (v) => setState(() => v == true ? chosen.add(c.address) : chosen.remove(c.address)),
                ),
              for (final m in chosen.where((m) => !s.contacts.any((c) => c.address == m)))
                CheckboxListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: Text(shortAddress(m), style: const TextStyle(fontFamily: 'monospace')),
                  value: true,
                  onChanged: (_) => setState(() => chosen.remove(m)),
                ),
              const SizedBox(height: 6),
              TextField(
                controller: extra,
                minLines: 1,
                maxLines: 3,
                autocorrect: false,
                style: const TextStyle(fontFamily: 'monospace', fontSize: 12.5),
                decoration: const InputDecoration(labelText: 'Other addresses (brry1…, one per line)', helperText: 'For people you have not written to yet'),
              ),
            ],
          ),
        ),
        actions: [
          if (existing != null) TextButton(onPressed: () => Navigator.pop(ctx, 'delete'), child: const Text('Disband crew', style: TextStyle(color: Palette.band))),
          TextButton(onPressed: () => Navigator.pop(ctx, null), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, 'save'), child: const Text('Save')),
        ],
      ),
    ),
  );
  if (result == 'delete' && existing != null) {
    await s.deleteGroup(existing.id);
    if (context.mounted) toast(context, 'Crew disbanded on this phone');
    return;
  }
  if (result != 'save') return;
  final typed = extra.text.split(RegExp(r'[\s,;]+')).map((x) => x.trim()).where((x) => x.isNotEmpty).toList();
  for (final t in typed) {
    if (!isValidAddress(t)) {
      if (context.mounted) toast(context, '$t is not a BerryChain address');
      return;
    }
    chosen.add(t);
  }
  chosen.remove(s.wallet?.address);
  if (name.text.trim().isEmpty) {
    if (context.mounted) toast(context, 'Give the crew a name');
    return;
  }
  if (chosen.length < 2) {
    if (context.mounted) toast(context, 'A crew needs at least two other people');
    return;
  }
  if (existing != null) await s.deleteGroup(existing.id);
  await s.saveGroup(name.text, chosen.toList());
  if (context.mounted) toast(context, 'Crew "${name.text.trim()}" saved. Send it a letter and everyone in it gets the crew too.');
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
      subtitle: Text('${shortAddress(c.address)}${c.name.isNotEmpty && c.nickname.isNotEmpty && !isHm ? ' · ${c.name}' : ''}${c.letters > 0 ? ' · ${c.letters} letter${c.letters == 1 ? '' : 's'}' : (isHm ? ' · answers every letter' : '')}',
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

/// A picker for the compose screen: returns a [Contact], a [LetterGroup], or null.
Future<Object?> pickRecipient(BuildContext context) {
  final s = SessionScope.of(context);
  return showModalBottomSheet<Object>(
    context: context,
    showDragHandle: true,
    builder: (ctx) => SessionScope(
      session: s,
      child: ListView(
        shrinkWrap: true,
        children: [
          if (s.groups.isNotEmpty) ...[
            const Padding(padding: EdgeInsets.fromLTRB(20, 0, 20, 4), child: Text('Write to a crew', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 16))),
            for (final g in s.groups) GroupRow(g, onPick: (picked) => Navigator.pop(ctx, picked)),
            const Divider(),
          ],
          const Padding(padding: EdgeInsets.fromLTRB(20, 0, 20, 4), child: Text('Write to', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 16))),
          for (final c in s.contacts) ContactRow(c, onPick: (picked) => Navigator.pop(ctx, picked)),
          const SizedBox(height: 12),
        ],
      ),
    ),
  );
}

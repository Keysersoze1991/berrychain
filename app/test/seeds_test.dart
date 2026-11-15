import 'dart:async';

import 'package:berrychain_app/core/node.dart';
import 'package:flutter_test/flutter_test.dart';

const quick = Duration(milliseconds: 40);

void main() {
  test('the seed in use answers: nobody else is asked', () async {
    final asked = <int>[];
    final (at, v) = await firstToAnswer(2, 0, (i) async { asked.add(i); return 'seed$i'; }, patience: quick);
    expect((at, v), (0, 'seed0'));
    await Future<void>.delayed(quick * 2);
    expect(asked, [0]);
  });

  test('a seed that fails is passed over at once', () async {
    final asked = <int>[];
    final (at, v) = await firstToAnswer<String>(2, 0, (i) async {
      asked.add(i);
      if (i == 0) throw NodeError('cannot reach seed0');
      return 'seed$i';
    }, patience: const Duration(seconds: 30));
    expect((at, v), (1, 'seed1'));
    expect(asked, [0, 1]);
  });

  test('a seed that keeps us waiting is overtaken by the next', () async {
    final slow = Completer<String>();
    final (at, v) = await firstToAnswer<String>(2, 0, (i) => i == 0 ? slow.future : Future.value('seed1'), patience: quick);
    expect((at, v), (1, 'seed1'));
    slow.complete('late');                       // the late answer is ignored, not an error
    await Future<void>.delayed(quick);
  });

  test('a slow seed that answers before the next one still wins', () async {
    final (at, v) = await firstToAnswer<String>(
        2, 0, (i) => Future.delayed(i == 0 ? quick * 2 : quick * 6, () => 'seed$i'), patience: quick);
    expect((at, v), (0, 'seed0'));
  });

  test('asking starts with the seed in use and goes round the list', () async {
    final asked = <int>[];
    final (at, _) = await firstToAnswer<String>(3, 2, (i) async {
      asked.add(i);
      if (i != 1) throw NodeError('cannot reach seed$i');
      return 'seed$i';
    }, patience: quick);
    expect(at, 1);
    expect(asked, [2, 0, 1]);
  });

  test('when no seed answers, the first failure is the one reported', () async {
    await expectLater(
        firstToAnswer<String>(2, 0, (i) async => throw NodeError('cannot reach seed$i'), patience: quick),
        throwsA(isA<NodeError>().having((e) => e.message, 'message', 'cannot reach seed0')));
  });

  test('a single seed: its answer, or its failure', () async {
    expect(await firstToAnswer(1, 0, (i) async => 'only', patience: quick), (0, 'only'));
    await expectLater(firstToAnswer<String>(1, 0, (i) async => throw NodeError('down'), patience: quick), throwsA(isA<NodeError>()));
  });
}

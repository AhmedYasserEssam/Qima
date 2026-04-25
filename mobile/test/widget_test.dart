import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:qima/main.dart';

void main() {
  testWidgets('renders the Qima contract client shell', (tester) async {
    await tester.pumpWidget(const ProviderScope(child: QimaApp()));
    await tester.pumpAndSettle();

    expect(find.text('Qima V1 Contract Client'), findsOneWidget);
    expect(find.text('Scan'), findsWidgets);
    expect(find.text('Recipes'), findsWidgets);
    expect(find.text('Plan'), findsWidgets);
    expect(find.text('Guidance'), findsWidgets);
    expect(find.text('Chat'), findsWidgets);
  });
}

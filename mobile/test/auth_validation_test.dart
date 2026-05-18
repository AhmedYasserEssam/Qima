import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/main.dart';

void main() {
  test('validateEmailAddress rejects empty emails', () {
    expect(validateEmailAddress('   '), 'Email is required.');
  });

  test('validateEmailAddress rejects malformed emails', () {
    expect(
      validateEmailAddress('invalid-email'),
      'Please enter a valid email address.',
    );
  });

  test('validateEmailAddress accepts valid emails', () {
    expect(validateEmailAddress('user@example.com'), isNull);
  });

  test('ApiFailure parses shared backend error payload', () {
    final failure = ApiFailure.fromResponse(409, {
      'error': {
        'code': 'ACCOUNT_ALREADY_EXISTS',
        'message':
            'An account with this email already exists. Please log in instead.',
        'retryable': false,
        'request_id': 'req_1234567890ab',
        'details': {},
      },
    });

    expect(failure.statusCode, 409);
    expect(failure.code, 'ACCOUNT_ALREADY_EXISTS');
    expect(
      failure.message,
      'An account with this email already exists. Please log in instead.',
    );
    expect(failure.retryable, isFalse);
  });
}

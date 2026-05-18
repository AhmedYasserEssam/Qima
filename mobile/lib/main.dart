import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:device_preview/device_preview.dart';
import 'package:flutter/foundation.dart';
import 'package:mobile/features/labs/data/lab_report_api_client.dart';
import 'package:mobile/features/labs/screens/lab_report_extract_test_screen.dart';

void main() {
  runApp(
    DevicePreview(
      enabled: !kReleaseMode,
      builder: (context) => const ProviderScope(child: QimaApp()),
    ),
  );
}

const _configuredApiBaseUrl = String.fromEnvironment('QIMA_API_BASE_URL');

String get apiBaseUrl {
  if (_configuredApiBaseUrl.isNotEmpty) {
    return _configuredApiBaseUrl;
  }
  if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
    return 'http://10.0.2.2:8000';
  }
  return 'http://127.0.0.1:8000';
}

final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(
    baseUrl: apiBaseUrl,
    client: http.Client(),
    authTokenReader: () => ref.read(authTokenProvider),
  );
});

final debugModeProvider = StateProvider<bool>((ref) => false);
final profileIdProvider = StateProvider<String?>((ref) => null);
final authTokenProvider = StateProvider<String?>((ref) => null);
final authBootstrappedProvider = StateProvider<bool>((ref) => false);
final authStageProvider = StateProvider<AuthStage>((ref) => AuthStage.booting);

const authTokenStorageKey = 'auth_token';
final _emailRegex = RegExp(r'^[^\s@]+@[^\s@]+\.[^\s@]+$');
const _secureTokenStorage = FlutterSecureStorage();

class AuthTokenStore {
  const AuthTokenStore();

  Future<void> writeToken(String? token) async {
    if (token == null || token.isEmpty) {
      await _deleteToken();
      return;
    }

    var storedInSecureStorage = false;
    try {
      await _secureTokenStorage.write(key: authTokenStorageKey, value: token);
      storedInSecureStorage = true;
    } on MissingPluginException {
      storedInSecureStorage = false;
    } on PlatformException {
      storedInSecureStorage = false;
    }

    final prefs = await SharedPreferences.getInstance();
    if (storedInSecureStorage) {
      await prefs.remove(authTokenStorageKey);
    } else {
      await prefs.setString(authTokenStorageKey, token);
    }
  }

  Future<String?> readToken() async {
    try {
      final token = await _secureTokenStorage.read(key: authTokenStorageKey);
      if (token != null && token.isNotEmpty) {
        return token;
      }
    } on MissingPluginException {
      // Fall back for tests and unsupported platforms.
    } on PlatformException {
      // Fall back when secure storage is unavailable at runtime.
    }

    final prefs = await SharedPreferences.getInstance();
    final legacyToken = prefs.getString(authTokenStorageKey);
    if (legacyToken == null || legacyToken.isEmpty) {
      return null;
    }
    return legacyToken;
  }

  Future<void> _deleteToken() async {
    try {
      await _secureTokenStorage.delete(key: authTokenStorageKey);
    } on MissingPluginException {
      // Ignore and clear fallback storage below.
    } on PlatformException {
      // Ignore and clear fallback storage below.
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(authTokenStorageKey);
  }
}

enum AuthStage { booting, loggedOut, needsProfile, ready }

Future<void> persistAuthToken(String? token) async {
  await const AuthTokenStore().writeToken(token);
}

Future<void> resolveAuthStage(WidgetRef ref) async {
  final token = ref.read(authTokenProvider);

  if (token == null || token.isEmpty) {
    ref.read(authStageProvider.notifier).state = AuthStage.loggedOut;
    return;
  }

  try {
    await ref
        .read(apiClientProvider)
        .get('/v1/profile/me', requiredFields: ['user_id']);
    ref.read(authStageProvider.notifier).state = AuthStage.ready;
  } on ApiFailure catch (error) {
    if (error.statusCode == 404) {
      ref.read(authStageProvider.notifier).state = AuthStage.needsProfile;
      return;
    }
    if (error.statusCode == 401) {
      await persistAuthToken(null);
      ref.read(authTokenProvider.notifier).state = null;
      ref.read(authStageProvider.notifier).state = AuthStage.loggedOut;
      return;
    }
    ref.read(authStageProvider.notifier).state = AuthStage.loggedOut;
  }
}

final healthProvider = FutureProvider<ApiPayload>((ref) async {
  return ref
      .read(apiClientProvider)
      .get('/v1/health', requiredFields: ['status']);
});

final routerProvider = Provider<GoRouter>((ref) {
  final bootstrapped = ref.watch(authBootstrappedProvider);
  final authStage = ref.watch(authStageProvider);
  return GoRouter(
    initialLocation: '/splash',
    redirect: (context, state) {
      final location = state.uri.path;
      final isSplash = location == '/splash';
      final isLogin = location == '/login';
      final isSignup = location == '/signup';
      final isProfileSetup = location == '/profile-setup';
      final isAuthRoute = isLogin || isSignup || isProfileSetup;

      if (!bootstrapped || authStage == AuthStage.booting) {
        return isSplash ? null : '/splash';
      }

      switch (authStage) {
        case AuthStage.loggedOut:
          return (isLogin || isSignup) ? null : '/login';
        case AuthStage.needsProfile:
          return isProfileSetup ? null : '/profile-setup';
        case AuthStage.ready:
          return (isAuthRoute || isSplash) ? '/scan' : null;
        case AuthStage.booting:
          return isSplash ? null : '/splash';
      }
    },
    routes: [
      GoRoute(
        path: '/splash',
        builder: (context, state) => const AuthSplashScreen(),
      ),
      GoRoute(path: '/login', builder: (context, state) => const LoginScreen()),
      GoRoute(
        path: '/signup',
        builder: (context, state) => const SignUpScreen(),
      ),
      GoRoute(
        path: '/profile-setup',
        builder: (context, state) => const ProfileSetupScreen(),
      ),
      ShellRoute(
        builder: (context, state, child) => AppShell(child: child),
        routes: [
          GoRoute(
            path: '/scan',
            builder: (context, state) => const ScanScreen(),
          ),
          GoRoute(
            path: '/recipes',
            builder: (context, state) => const RecipesScreen(),
          ),
          GoRoute(
            path: '/plan',
            builder: (context, state) => const PlanScreen(),
          ),
          GoRoute(
            path: '/guidance',
            builder: (context, state) => const GuidanceScreen(),
          ),
          GoRoute(
            path: '/chat',
            builder: (context, state) => const ChatScreen(),
          ),
          GoRoute(
            path: '/profile',
            builder: (context, state) => const ProfileScreen(),
          ),
          GoRoute(
            path: '/debug',
            builder: (context, state) => const DebugScreen(),
          ),
          GoRoute(
            path: '/labs/extract-report-test',
            builder: (context, state) => LabReportExtractTestScreen(
              baseUrl: apiBaseUrl,
              apiClient: LabReportApiClient(
                baseUrl: apiBaseUrl,
                authTokenReader: () => ref.read(authTokenProvider),
              ),
            ),
          ),
          GoRoute(
            path: '/barcode-scanner',
            builder: (context, state) => const BarcodeScannerScreen(),
          ),
        ],
      ),
    ],
  );
});

class QimaApp extends ConsumerStatefulWidget {
  const QimaApp({super.key});

  @override
  ConsumerState<QimaApp> createState() => _QimaAppState();
}

class _QimaAppState extends ConsumerState<QimaApp> {
  @override
  void initState() {
    super.initState();
    unawaited(_loadLocalState());
  }

  Future<void> _loadLocalState() async {
    final prefs = await SharedPreferences.getInstance();
    ref.read(profileIdProvider.notifier).state = prefs.getString('profile_id');
    ref.read(authTokenProvider.notifier).state = await const AuthTokenStore()
        .readToken();
    await resolveAuthStage(ref);
    ref.read(authBootstrappedProvider.notifier).state = true;
  }

  @override
  Widget build(BuildContext context) {
    final router = ref.watch(routerProvider);
    return MaterialApp.router(
      locale: DevicePreview.locale(context),
      builder: DevicePreview.appBuilder,
      title: 'Qima',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff207567)),
        useMaterial3: true,
        cardTheme: const CardThemeData(
          margin: EdgeInsets.symmetric(vertical: 8),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.all(Radius.circular(8)),
          ),
        ),
      ),
      routerConfig: router,
    );
  }
}

class AuthSplashScreen extends StatelessWidget {
  const AuthSplashScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return const Scaffold(body: Center(child: CircularProgressIndicator()));
  }
}

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final emailController = TextEditingController();
  final passwordController = TextEditingController();
  bool busy = false;
  String? feedback;
  bool isError = false;

  @override
  void dispose() {
    emailController.dispose();
    passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Login')),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        'Sign in to access Qima',
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: emailController,
                        keyboardType: TextInputType.emailAddress,
                        decoration: const InputDecoration(labelText: 'Email'),
                      ),
                      const SizedBox(height: 8),
                      TextFormField(
                        controller: passwordController,
                        obscureText: true,
                        decoration: const InputDecoration(
                          labelText: 'Password',
                        ),
                      ),
                      const SizedBox(height: 12),
                      FilledButton.icon(
                        onPressed: busy ? null : _login,
                        icon: const Icon(Icons.login),
                        label: const Text('Log in'),
                      ),
                      const SizedBox(height: 8),
                      OutlinedButton(
                        onPressed: busy ? null : () => context.go('/signup'),
                        child: const Text('Create account'),
                      ),
                      if (busy) ...[
                        const SizedBox(height: 12),
                        const Center(child: CircularProgressIndicator()),
                      ],
                      if (feedback != null) ...[
                        const SizedBox(height: 12),
                        Container(
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(8),
                            color: isError
                                ? colorScheme.errorContainer
                                : colorScheme.primaryContainer,
                          ),
                          child: Text(
                            feedback!,
                            style: TextStyle(
                              color: isError
                                  ? colorScheme.onErrorContainer
                                  : colorScheme.onPrimaryContainer,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _login() async {
    final emailInput = emailController.text;
    final email = emailInput.trim().toLowerCase();
    final password = passwordController.text;
    final emailError = validateEmailAddress(emailInput);
    if (emailError != null) {
      showValidation(context, emailError);
      return;
    }
    if (password.trim().isEmpty) {
      showValidation(context, 'Password is required.');
      return;
    }

    setState(() {
      busy = true;
      feedback = null;
    });

    try {
      final payload = await ref
          .read(apiClientProvider)
          .post(
            '/v1/auth/login',
            {'email': email, 'password': password},
            requiredFields: ['message', 'access_token', 'token_type', 'user'],
          );
      final token = text(payload.raw['access_token'], fallback: '').trim();
      if (token.isEmpty) {
        throw ApiFailure(
          message: 'Login succeeded but no access token was returned.',
          retryable: false,
        );
      }
      await persistAuthToken(token);
      ref.read(authTokenProvider.notifier).state = token;
      await resolveAuthStage(ref);
      if (mounted) {
        context.go('/scan');
      }
    } on ApiFailure catch (error) {
      _setFeedback(error.message, isErrorValue: true);
    } finally {
      if (mounted) {
        setState(() => busy = false);
      }
    }
  }

  void _setFeedback(String message, {bool isErrorValue = false}) {
    if (!mounted) {
      return;
    }
    setState(() {
      feedback = message;
      isError = isErrorValue;
    });
  }
}

class SignUpScreen extends ConsumerStatefulWidget {
  const SignUpScreen({super.key});

  @override
  ConsumerState<SignUpScreen> createState() => _SignUpScreenState();
}

class _SignUpScreenState extends ConsumerState<SignUpScreen> {
  final nameController = TextEditingController();
  final emailController = TextEditingController();
  final passwordController = TextEditingController();
  bool busy = false;
  String? feedback;
  bool isError = false;

  @override
  void dispose() {
    nameController.dispose();
    emailController.dispose();
    passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Sign Up')),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text(
                        'Create your account',
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 12),
                      TextFormField(
                        controller: nameController,
                        keyboardType: TextInputType.name,
                        textCapitalization: TextCapitalization.words,
                        decoration: const InputDecoration(
                          labelText: 'Full name',
                        ),
                      ),
                      const SizedBox(height: 8),
                      TextFormField(
                        controller: emailController,
                        keyboardType: TextInputType.emailAddress,
                        decoration: const InputDecoration(labelText: 'Email'),
                      ),
                      const SizedBox(height: 8),
                      TextFormField(
                        controller: passwordController,
                        obscureText: true,
                        decoration: const InputDecoration(
                          labelText: 'Password',
                        ),
                      ),
                      const SizedBox(height: 12),
                      FilledButton.icon(
                        onPressed: busy ? null : _signup,
                        icon: const Icon(Icons.person_add_alt_1),
                        label: const Text('Create account'),
                      ),
                      const SizedBox(height: 8),
                      TextButton(
                        onPressed: busy ? null : () => context.go('/login'),
                        child: const Text('Back to login'),
                      ),
                      if (busy) ...[
                        const SizedBox(height: 12),
                        const Center(child: CircularProgressIndicator()),
                      ],
                      if (feedback != null) ...[
                        const SizedBox(height: 12),
                        Container(
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(8),
                            color: isError
                                ? colorScheme.errorContainer
                                : colorScheme.primaryContainer,
                          ),
                          child: Text(
                            feedback!,
                            style: TextStyle(
                              color: isError
                                  ? colorScheme.onErrorContainer
                                  : colorScheme.onPrimaryContainer,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _signup() async {
    final name = nameController.text.trim();
    final emailInput = emailController.text;
    final email = emailInput.trim().toLowerCase();
    final password = passwordController.text;
    if (name.isEmpty) {
      showValidation(context, 'Name is required.');
      return;
    }
    final emailError = validateEmailAddress(emailInput);
    if (emailError != null) {
      showValidation(context, emailError);
      return;
    }
    if (password.trim().isEmpty) {
      showValidation(context, 'Password is required.');
      return;
    }

    setState(() {
      busy = true;
      feedback = null;
    });

    try {
      final payload = await ref
          .read(apiClientProvider)
          .post(
            '/v1/auth/signup',
            {'email': email, 'password': password, 'name': name},
            requiredFields: ['message', 'user'],
          );

      if (mounted) {
        showValidation(
          context,
          text(
            payload.raw['message'],
            fallback: 'Account created successfully. You can now log in.',
          ),
        );
        context.go('/login');
      }
    } on ApiFailure catch (error) {
      _setFeedback(error.message, isErrorValue: true);
    } finally {
      if (mounted) {
        setState(() => busy = false);
      }
    }
  }

  void _setFeedback(String message, {bool isErrorValue = false}) {
    if (!mounted) {
      return;
    }
    setState(() {
      feedback = message;
      isError = isErrorValue;
    });
  }
}

class ProfileSetupScreen extends ConsumerStatefulWidget {
  const ProfileSetupScreen({super.key});

  @override
  ConsumerState<ProfileSetupScreen> createState() => _ProfileSetupScreenState();
}

class _ProfileSetupScreenState extends ConsumerState<ProfileSetupScreen> {
  final ageController = TextEditingController(text: '30');
  final heightController = TextEditingController(text: '170');
  final weightController = TextEditingController(text: '70');
  final allergensController = TextEditingController();
  final dietaryRestrictionsController = TextEditingController();
  final safetyScreening = defaultSafetyScreening();
  String sex = 'male';
  String activity = 'moderately_active';
  String goal = 'improve_general_health';
  bool agreementAccepted = false;
  bool busy = false;
  String? feedback;
  bool isError = false;

  @override
  void dispose() {
    ageController.dispose();
    heightController.dispose();
    weightController.dispose();
    allergensController.dispose();
    dietaryRestrictionsController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Complete Profile Setup'),
        actions: [
          IconButton(
            tooltip: 'Logout',
            onPressed: busy
                ? null
                : () async {
                    await persistAuthToken(null);
                    ref.read(authTokenProvider.notifier).state = null;
                    ref.read(authStageProvider.notifier).state =
                        AuthStage.loggedOut;
                    if (context.mounted) {
                      context.go('/login');
                    }
                  },
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 600),
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const NoticeCard(
                        icon: Icons.lock_outline,
                        title: 'Mandatory Step',
                        message:
                            'You must complete your profile before accessing app features.',
                      ),
                      TextFormField(
                        controller: ageController,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(labelText: 'Age'),
                      ),
                      TextFormField(
                        controller: heightController,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(
                          labelText: 'Height cm',
                        ),
                      ),
                      TextFormField(
                        controller: weightController,
                        keyboardType: TextInputType.number,
                        decoration: const InputDecoration(
                          labelText: 'Weight kg',
                        ),
                      ),
                      DropdownButtonFormField<String>(
                        initialValue: sex,
                        decoration: const InputDecoration(labelText: 'Sex'),
                        items: options(['male', 'female']),
                        onChanged: (value) =>
                            setState(() => sex = value ?? sex),
                      ),
                      DropdownButtonFormField<String>(
                        initialValue: activity,
                        decoration: const InputDecoration(
                          labelText: 'Activity level',
                        ),
                        items: options([
                          'sedentary',
                          'lightly_active',
                          'moderately_active',
                          'very_active',
                          'athlete',
                        ]),
                        onChanged: (value) =>
                            setState(() => activity = value ?? activity),
                      ),
                      DropdownButtonFormField<String>(
                        initialValue: goal,
                        decoration: const InputDecoration(
                          labelText: 'Nutrition goal',
                        ),
                        items: options([
                          'lose_weight',
                          'maintain_weight',
                          'gain_weight',
                          'build_muscle',
                          'improve_general_health',
                          'eat_high_protein',
                          'eat_low_calorie',
                          'eat_balanced',
                          'reduce_sugar',
                          'reduce_sodium',
                          'reduce_saturated_fat',
                          'increase_fiber',
                        ]),
                        onChanged: (value) =>
                            setState(() => goal = value ?? goal),
                      ),
                      TextFormField(
                        controller: allergensController,
                        decoration: const InputDecoration(
                          labelText: 'Allergens (comma-separated)',
                        ),
                      ),
                      TextFormField(
                        controller: dietaryRestrictionsController,
                        decoration: const InputDecoration(
                          labelText: 'Dietary restrictions (comma-separated)',
                        ),
                      ),
                      const SizedBox(height: 16),
                      SafetyScreeningSection(
                        values: safetyScreening,
                        onChanged: _setSafetyScreening,
                      ),
                      const SizedBox(height: 16),
                      AgreementSection(
                        accepted: agreementAccepted,
                        onChanged: (value) =>
                            setState(() => agreementAccepted = value),
                      ),
                      const SizedBox(height: 12),
                      FilledButton.icon(
                        onPressed: busy ? null : _submitProfile,
                        icon: const Icon(Icons.check_circle_outline),
                        label: const Text('Finish onboarding'),
                      ),
                      if (busy) ...[
                        const SizedBox(height: 12),
                        const Center(child: CircularProgressIndicator()),
                      ],
                      if (feedback != null) ...[
                        const SizedBox(height: 12),
                        Container(
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(8),
                            color: isError
                                ? colorScheme.errorContainer
                                : colorScheme.primaryContainer,
                          ),
                          child: Text(
                            feedback!,
                            style: TextStyle(
                              color: isError
                                  ? colorScheme.onErrorContainer
                                  : colorScheme.onPrimaryContainer,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _submitProfile() async {
    final body = _buildProfileBody();
    if (body == null) {
      return;
    }

    setState(() {
      busy = true;
      feedback = null;
    });

    try {
      await ref
          .read(apiClientProvider)
          .post(
            '/v1/profile/update',
            body,
            requiredFields: [
              'user_id',
              'goal',
              'safety_screening',
              'agreement_accepted',
              'updated_at',
            ],
          );
      await resolveAuthStage(ref);
      if (mounted) {
        context.go('/scan');
      }
    } on ApiFailure catch (error) {
      _setFeedback(error.message, isErrorValue: true);
    } finally {
      if (mounted) {
        setState(() => busy = false);
      }
    }
  }

  Map<String, Object?>? _buildProfileBody() {
    final age = int.tryParse(ageController.text.trim());
    final height = double.tryParse(heightController.text.trim());
    final weight = double.tryParse(weightController.text.trim());

    if (age == null || age < 1 || height == null || weight == null) {
      showValidation(context, 'Please provide valid age, height, and weight.');
      return null;
    }
    if (!safetyScreeningCompleted(safetyScreening)) {
      showValidation(
        context,
        'Please complete the Safety Screening before continuing.',
      );
      return null;
    }
    if (!agreementAccepted) {
      showValidation(context, agreementValidationMessage);
      return null;
    }

    final allergens = allergensController.text
        .split(',')
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();
    final restrictions = dietaryRestrictionsController.text
        .split(',')
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();

    return {
      'age': age,
      'sex': sex,
      'height_cm': height,
      'weight_kg': weight,
      'activity_level': activity,
      'goal': goal,
      'allergens': allergens,
      'dietary_restrictions': restrictions,
      'safety_screening': safetyScreeningBody(safetyScreening),
      'agreement_accepted': agreementAccepted,
    };
  }

  void _setSafetyScreening(String key, bool value) {
    setState(() => updateSafetyScreening(safetyScreening, key, value));
  }

  void _setFeedback(String message, {bool isErrorValue = false}) {
    if (!mounted) {
      return;
    }
    setState(() {
      feedback = message;
      isError = isErrorValue;
    });
  }
}

class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.child});

  final Widget child;

  static const tabs = [
    ('/scan', 'Scan', Icons.document_scanner_outlined),
    ('/recipes', 'Recipes', Icons.restaurant_menu_outlined),
    ('/plan', 'Plan', Icons.event_note_outlined),
    ('/guidance', 'Guidance', Icons.health_and_safety_outlined),
    ('/chat', 'Chat', Icons.chat_bubble_outline),
  ];

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final location = GoRouterState.of(context).uri.path;
    final selectedIndex = tabs.indexWhere((tab) => location.startsWith(tab.$1));
    final profileId = ref.watch(profileIdProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Qima V1 Contract Client'),
        actions: [
          IconButton(
            tooltip: 'Logout',
            onPressed: () async {
              await persistAuthToken(null);
              ref.read(authTokenProvider.notifier).state = null;
              ref.read(authStageProvider.notifier).state = AuthStage.loggedOut;
              if (context.mounted) {
                context.go('/login');
              }
            },
            icon: const Icon(Icons.logout),
          ),
          IconButton(
            tooltip: 'Profile',
            onPressed: () => context.go('/profile'),
            icon: Badge(
              isLabelVisible: profileId != null,
              child: const Icon(Icons.person_outline),
            ),
          ),
          IconButton(
            tooltip: 'Debug and backend health',
            onPressed: () => context.go('/debug'),
            icon: const Icon(Icons.bug_report_outlined),
          ),
        ],
      ),
      body: SafeArea(child: child),
      bottomNavigationBar: NavigationBar(
        selectedIndex: selectedIndex < 0 ? 0 : selectedIndex,
        onDestinationSelected: (index) => context.go(tabs[index].$1),
        destinations: [
          for (final tab in tabs)
            NavigationDestination(
              icon: Icon(tab.$3),
              label: tab.$2,
              tooltip: tab.$2,
            ),
        ],
      ),
    );
  }
}

class ApiClient {
  ApiClient({
    required this.baseUrl,
    required this.client,
    required this.authTokenReader,
  });

  static const requestTimeout = Duration(seconds: 12);
  static const recipeTimeout = Duration(seconds: 60);
  static const planTimeout = Duration(seconds: 120);
  static const uploadTimeout = Duration(seconds: 45);

  final String baseUrl;
  final http.Client client;
  final String? Function() authTokenReader;

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Map<String, String> _headers({bool includeJsonContentType = false}) {
    final headers = <String, String>{};
    if (includeJsonContentType) {
      headers['content-type'] = 'application/json';
    }
    final token = authTokenReader();
    if (token != null && token.isNotEmpty) {
      headers['authorization'] = 'Bearer $token';
    }
    return headers;
  }

  Future<ApiPayload> get(
    String path, {
    required List<String> requiredFields,
  }) async {
    try {
      final response = await client
          .get(_uri(path), headers: _headers())
          .timeout(requestTimeout);
      return _parseResponse(response, requiredFields);
    } on ApiFailure {
      rethrow;
    } on TimeoutException {
      throw ApiFailure.timeout(requestTimeout);
    } on Exception catch (error) {
      throw ApiFailure.network(error.toString());
    }
  }

  Future<ApiPayload> post(
    String path,
    Map<String, Object?> body, {
    required List<String> requiredFields,
    Duration timeout = requestTimeout,
  }) async {
    try {
      final response = await client
          .post(
            _uri(path),
            headers: _headers(includeJsonContentType: true),
            body: jsonEncode(body),
          )
          .timeout(timeout);
      return _parseResponse(response, requiredFields);
    } on ApiFailure {
      rethrow;
    } on TimeoutException {
      throw ApiFailure.timeout(timeout);
    } on Exception catch (error) {
      throw ApiFailure.network(error.toString());
    }
  }

  Future<ApiPayload> delete(
    String path, {
    required List<String> requiredFields,
  }) async {
    try {
      final response = await client
          .delete(_uri(path), headers: _headers())
          .timeout(requestTimeout);
      return _parseResponse(response, requiredFields);
    } on ApiFailure {
      rethrow;
    } on TimeoutException {
      throw ApiFailure.timeout(requestTimeout);
    } on Exception catch (error) {
      throw ApiFailure.network(error.toString());
    }
  }

  Future<ApiPayload> uploadImage(
    String path,
    XFile image, {
    required List<String> requiredFields,
  }) async {
    try {
      final imageBytes = await image.readAsBytes();
      final request = http.MultipartRequest('POST', _uri(path))
        ..headers.addAll(_headers())
        ..fields['locale'] = 'en'
        ..files.add(
          http.MultipartFile.fromBytes(
            'image',
            imageBytes,
            filename: image.name,
          ),
        );
      final streamed = await client.send(request).timeout(uploadTimeout);
      final response = await http.Response.fromStream(streamed);
      return _parseResponse(response, requiredFields);
    } on ApiFailure {
      rethrow;
    } on TimeoutException {
      throw ApiFailure.timeout(uploadTimeout);
    } on Exception catch (error) {
      throw ApiFailure.network(error.toString());
    }
  }

  ApiPayload _parseResponse(
    http.Response response,
    List<String> requiredFields,
  ) {
    final decoded = _decodeObject(response.body);
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiFailure.fromResponse(response.statusCode, decoded);
    }

    final issues = <String>[];
    for (final field in requiredFields) {
      if (!decoded.containsKey(field) || decoded[field] == null) {
        issues.add('Missing required field: $field');
      }
    }

    return ApiPayload(
      raw: decoded,
      contractIssues: issues,
      partialReasons: detectPartialReasons(decoded),
    );
  }

  Map<String, Object?> _decodeObject(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        return decoded.cast<String, Object?>();
      }
      return {'value': decoded};
    } on FormatException {
      return {'body': body};
    }
  }
}

class ApiPayload {
  ApiPayload({
    required this.raw,
    required this.contractIssues,
    required this.partialReasons,
  });

  final Map<String, Object?> raw;
  final List<String> contractIssues;
  final List<String> partialReasons;

  bool get hasContractIssues => contractIssues.isNotEmpty;
  bool get isPartial => partialReasons.isNotEmpty;
}

class ApiFailure implements Exception {
  ApiFailure({
    required this.message,
    required this.retryable,
    this.statusCode,
    this.code,
    this.details,
  });

  factory ApiFailure.network(String details) {
    return ApiFailure(
      message: 'Could not reach the FastAPI backend.',
      retryable: true,
      code: 'NETWORK_ERROR',
      details: details,
    );
  }

  factory ApiFailure.timeout(Duration timeout) {
    return ApiFailure(
      message:
          'The FastAPI backend took too long to respond. It may still be warming up.',
      retryable: true,
      code: 'TIMEOUT',
      details: 'Request timed out after $timeout.',
    );
  }

  factory ApiFailure.fromResponse(int statusCode, Map<String, Object?> raw) {
    final error = raw['error'];
    if (error is Map) {
      final code = text(error['code'], fallback: '').trim();
      return ApiFailure(
        message: text(error['message'], fallback: 'Request failed.'),
        retryable: error['retryable'] == true,
        statusCode: statusCode,
        code: code.isEmpty ? null : code,
        details: jsonEncode(raw),
      );
    }
    final detail = raw['detail'];
    if (detail is String && detail.trim().isNotEmpty) {
      return ApiFailure(
        message: detail.trim(),
        retryable: statusCode >= 500 || statusCode == 429,
        statusCode: statusCode,
        code: null,
        details: jsonEncode(raw),
      );
    }
    if (detail is List && detail.isNotEmpty) {
      final first = detail.first;
      if (first is Map) {
        final msg = text(first['msg'], fallback: '').trim();
        if (msg.isNotEmpty) {
          return ApiFailure(
            message: msg,
            retryable: statusCode >= 500 || statusCode == 429,
            statusCode: statusCode,
            code: null,
            details: jsonEncode(raw),
          );
        }
      }
    }
    return ApiFailure(
      message: 'Request failed with HTTP $statusCode.',
      retryable: statusCode >= 500 || statusCode == 429,
      statusCode: statusCode,
      code: null,
      details: jsonEncode(raw),
    );
  }

  final String message;
  final bool retryable;
  final int? statusCode;
  final String? code;
  final String? details;

  @override
  String toString() => message;
}

List<String> detectPartialReasons(Map<String, Object?> raw) {
  final reasons = <String>[];
  final quality = raw['data_quality'];
  if (quality is Map && quality['completeness'] == 'partial') {
    reasons.add('Data quality is partial.');
  }
  final confidence = number(raw['confidence']);
  if (confidence != null && confidence < 0.7) {
    reasons.add('Confidence is low.');
  }
  final missing = raw['missing_ingredients'];
  final missingInput = raw['missing_input_ingredients'];
  if ((missing is List && missing.isNotEmpty) ||
      (missingInput is List && missingInput.isNotEmpty)) {
    reasons.add('Some ingredients are missing.');
  }
  final recipes = raw['recipes'];
  if (recipes is List) {
    for (final recipe in recipes) {
      if (recipe is Map &&
          ((recipe['missing_ingredients'] is List &&
                  (recipe['missing_ingredients'] as List).isNotEmpty) ||
              (recipe['missing_input_ingredients'] is List &&
                  (recipe['missing_input_ingredients'] as List).isNotEmpty))) {
        reasons.add('Recipe suggestions include missing ingredients.');
        break;
      }
    }
  }
  final meals = raw['meals'];
  if (meals is List) {
    for (final meal in meals) {
      if (meal is Map &&
          meal['estimated_cost'] is Map &&
          (meal['estimated_cost'] as Map)['estimate_quality'] != 'complete') {
        reasons.add('Meal costs are partial estimates.');
        break;
      }
    }
  }
  final support = raw['support_status'];
  if (support is Map &&
      support['status'] != null &&
      support['status'] != 'supported') {
    reasons.add('Guidance is ${support['status']}.');
  }
  final estimateQuality = raw['estimate_quality'];
  if (estimateQuality is Map) {
    final quality = estimateQuality['overall'] ?? estimateQuality['coverage'];
    if (quality != null && quality != 'complete') {
      reasons.add('Price estimate is $quality.');
    }
  }
  return reasons.toSet().toList();
}

class EndpointController extends StateNotifier<AsyncValue<ApiPayload>?> {
  EndpointController(this._client) : super(null);

  final ApiClient _client;

  Future<ApiPayload?> run(
    Future<ApiPayload> Function(ApiClient client) action,
  ) async {
    state = const AsyncValue.loading();
    final nextState = await AsyncValue.guard(() => action(_client));
    state = nextState;
    return nextState.valueOrNull;
  }

  void clear() => state = null;
}

final scanControllerProvider =
    StateNotifierProvider<EndpointController, AsyncValue<ApiPayload>?>(
      (ref) => EndpointController(ref.read(apiClientProvider)),
    );
final nutritionControllerProvider =
    StateNotifierProvider<EndpointController, AsyncValue<ApiPayload>?>(
      (ref) => EndpointController(ref.read(apiClientProvider)),
    );
final recipeControllerProvider =
    StateNotifierProvider<EndpointController, AsyncValue<ApiPayload>?>(
      (ref) => EndpointController(ref.read(apiClientProvider)),
    );
final recipeDiscussControllerProvider =
    StateNotifierProvider<EndpointController, AsyncValue<ApiPayload>?>(
      (ref) => EndpointController(ref.read(apiClientProvider)),
    );
final profileControllerProvider =
    StateNotifierProvider<EndpointController, AsyncValue<ApiPayload>?>(
      (ref) => EndpointController(ref.read(apiClientProvider)),
    );
final planControllerProvider =
    StateNotifierProvider<EndpointController, AsyncValue<ApiPayload>?>(
      (ref) => EndpointController(ref.read(apiClientProvider)),
    );
final labsControllerProvider =
    StateNotifierProvider<EndpointController, AsyncValue<ApiPayload>?>(
      (ref) => EndpointController(ref.read(apiClientProvider)),
    );
final chatControllerProvider =
    StateNotifierProvider<EndpointController, AsyncValue<ApiPayload>?>(
      (ref) => EndpointController(ref.read(apiClientProvider)),
    );

final inventoryControllerProvider =
    StateNotifierProvider<
      InventoryController,
      AsyncValue<List<InventoryItemRecord>>
    >((ref) => InventoryController(ref.read(apiClientProvider)));
final selectedVisionIngredientsProvider = StateProvider<List<String>>(
  (ref) => const <String>[],
);

class InventoryController
    extends StateNotifier<AsyncValue<List<InventoryItemRecord>>> {
  InventoryController(this._client) : super(const AsyncValue.loading()) {
    unawaited(refresh());
  }

  final ApiClient _client;

  Future<void> refresh() async {
    state = const AsyncValue.loading();
    await _sync();
  }

  Future<void> addManualItems(List<String> itemNames) async {
    final body = buildInventoryManualAddBody(itemNames);
    await _client.post(
      '/v1/inventory/items/manual',
      body,
      requiredFields: ['items'],
    );
    await _sync();
  }

  Future<void> addFromImageSelection(InventoryImageSelection selection) async {
    final body = buildInventoryImageAddBody(selection);
    await _client.post(
      '/v1/inventory/items/from-image',
      body,
      requiredFields: ['items'],
    );
    await _sync();
  }

  Future<void> addFromBarcode(String barcode) async {
    await _client.post(
      '/v1/inventory/items/from-barcode',
      {'barcode': barcode},
      requiredFields: ['items'],
    );
    await _sync();
  }

  Future<void> deleteItem(int itemId) async {
    await _client.delete(
      '/v1/inventory/items/$itemId',
      requiredFields: ['deleted_item_id'],
    );
    await _sync();
  }

  Future<InventoryClearResult> clearAll() async {
    final current = state.valueOrNull ?? await _fetchItems();
    var deletedCount = 0;
    final failedIds = <int>[];

    for (final item in current) {
      try {
        await _client.delete(
          '/v1/inventory/items/${item.id}',
          requiredFields: ['deleted_item_id'],
        );
        deletedCount += 1;
      } on ApiFailure {
        failedIds.add(item.id);
      }
    }

    await _sync();
    return InventoryClearResult(
      deletedCount: deletedCount,
      failedIds: failedIds,
    );
  }

  Future<void> _sync() async {
    try {
      final items = await _fetchItems();
      state = AsyncValue.data(items);
    } catch (error, stackTrace) {
      state = AsyncValue.error(error, stackTrace);
      rethrow;
    }
  }

  Future<List<InventoryItemRecord>> _fetchItems() async {
    final payload = await _client.get(
      '/v1/inventory/items',
      requiredFields: ['items'],
    );
    return inventoryItemsFromPayload(payload.raw);
  }
}

class InventoryClearResult {
  const InventoryClearResult({
    required this.deletedCount,
    required this.failedIds,
  });

  final int deletedCount;
  final List<int> failedIds;

  int get failedCount => failedIds.length;
}

const noReliableVisionNutritionInputMessage =
    'No reliable nutrition input was found from this image.';

class ScanScreen extends ConsumerStatefulWidget {
  const ScanScreen({super.key});

  @override
  ConsumerState<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends ConsumerState<ScanScreen> {
  final barcodeController = TextEditingController(text: '5449000000996');
  final dishController = TextEditingController(text: 'koshari');
  final ScrollController _scrollController = ScrollController();
  final GlobalKey _scanResultKey = GlobalKey();
  Map<String, Object?>? _lastNutritionRequestBody;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final current = ref.read(scanControllerProvider);
      if (current is AsyncData<ApiPayload>) {
        _scrollToScanResult();
      }
    });
  }

  @override
  void dispose() {
    barcodeController.dispose();
    dishController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<AsyncValue<ApiPayload>?>(scanControllerProvider, (
      previous,
      next,
    ) {
      final didBecomeSuccessful =
          (next is AsyncData<ApiPayload>) &&
          (previous is! AsyncData<ApiPayload>);
      if (didBecomeSuccessful) {
        _scrollToScanResult();
      }
    });

    final scanState = ref.watch(scanControllerProvider);
    final nutritionState = ref.watch(nutritionControllerProvider);
    return EndpointPage(
      title: 'Scan',
      scrollController: _scrollController,
      children: [
        InputCard(
          title: 'Barcode lookup',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                controller: barcodeController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Barcode',
                  helperText: '8 to 14 digits',
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  FilledButton.icon(
                    onPressed: _lookupBarcode,
                    icon: const Icon(Icons.search),
                    label: const Text('Lookup'),
                  ),
                  OutlinedButton.icon(
                    onPressed: () => context.go('/barcode-scanner'),
                    icon: const Icon(Icons.document_scanner_outlined),
                    label: const Text('Open scanner'),
                  ),
                ],
              ),
            ],
          ),
        ),
        InputCard(
          title: 'Food image upload',
          child: Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              FilledButton.icon(
                onPressed: () => _pickImage(ImageSource.gallery),
                icon: const Icon(Icons.upload_file),
                label: const Text('Upload image'),
              ),
              OutlinedButton.icon(
                onPressed: () => _pickImage(ImageSource.camera),
                icon: const Icon(Icons.camera_alt_outlined),
                label: const Text('Capture image'),
              ),
            ],
          ),
        ),
        InputCard(
          title: 'Nutrition estimate',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                controller: dishController,
                decoration: const InputDecoration(labelText: 'Recognized dish'),
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: _estimateNutrition,
                icon: const Icon(Icons.calculate_outlined),
                label: const Text('Estimate nutrition'),
              ),
            ],
          ),
        ),
        Container(
          key: _scanResultKey,
          child: AsyncPayloadView(
            title: 'Scan result',
            value: scanState,
            onRetry: _lookupBarcode,
            onEstimateNutritionFromVision: _estimateNutritionFromVision,
            onAddBarcodeToInventory: _addBarcodeScanToInventory,
            onAddInventoryFromVision: _addVisionIngredientsToInventory,
            onVisionSelectionChanged: _setVisionSelectionForRecipes,
          ),
        ),
        AsyncPayloadView(
          title: 'Nutrition estimate',
          value: nutritionState,
          onRetry: _retryNutritionEstimate,
        ),
      ],
    );
  }

  void _lookupBarcode() {
    final barcode = barcodeController.text.trim();
    if (!RegExp(r'^[0-9]{8,14}$').hasMatch(barcode)) {
      showValidation(context, 'Barcode must contain 8 to 14 digits.');
      return;
    }
    ref
        .read(scanControllerProvider.notifier)
        .run(
          (client) => client.post(
            '/v1/barcode/lookup',
            {'barcode': barcode},
            requiredFields: ['product_id', 'name', 'nutrition', 'source'],
          ),
        );
  }

  Future<void> _pickImage(ImageSource source) async {
    final image = await ImagePicker().pickImage(source: source);
    if (image == null) {
      return;
    }
    await ref
        .read(scanControllerProvider.notifier)
        .run(
          (client) => client.uploadImage(
            '/v1/vision/identify',
            image,
            requiredFields: [
              'image_id',
              'dish_candidates',
              'ingredients',
              'source',
            ],
          ),
        );
  }

  void _estimateNutrition() {
    final dish = dishController.text.trim();
    if (dish.isEmpty) {
      showValidation(context, 'Recognized dish is required.');
      return;
    }
    _submitNutritionEstimate(<String, Object?>{
      'input_type': 'recognized_dish',
      'recognized_dish': dish,
    });
  }

  void _retryNutritionEstimate() {
    final body = _lastNutritionRequestBody;
    if (body == null) {
      _estimateNutrition();
      return;
    }
    _submitNutritionEstimate(body);
  }

  void _estimateNutritionFromVision(Map<String, Object?> raw) {
    final body = nutritionRequestBodyFromVisionPayload(raw);
    if (body == null) {
      showValidation(context, noReliableVisionNutritionInputMessage);
      return;
    }

    if (body['input_type'] == 'recognized_dish') {
      final dish = text(body['recognized_dish'], fallback: '').trim();
      if (dish.isNotEmpty) {
        dishController.text = dish;
      }
    }
    _submitNutritionEstimate(body);
  }

  void _submitNutritionEstimate(Map<String, Object?> body) {
    _lastNutritionRequestBody = Map<String, Object?>.from(body);
    ref
        .read(nutritionControllerProvider.notifier)
        .run(
          (client) => client.post(
            '/v1/nutrition/estimate',
            body,
            requiredFields: [
              'matched_dish',
              'nutrients',
              'confidence',
              'source',
            ],
          ),
        );
  }

  Future<void> _addBarcodeScanToInventory(Map<String, Object?> raw) async {
    final barcode = inventoryBarcodeFromScanPayload(raw);
    if (barcode == null) {
      showValidation(
        context,
        'Could not determine a valid barcode from this result.',
      );
      return;
    }

    try {
      await ref
          .read(inventoryControllerProvider.notifier)
          .addFromBarcode(barcode);
      if (mounted) {
        showValidation(context, 'Added to inventory.');
      }
    } on ApiFailure catch (error) {
      if (mounted) {
        showValidation(context, error.message);
      }
    }
  }

  Future<void> _addVisionIngredientsToInventory(
    InventoryImageSelection selection,
  ) async {
    if (selection.selectedIngredients.isEmpty) {
      showValidation(context, 'Select at least one ingredient to add.');
      return;
    }
    try {
      await ref
          .read(inventoryControllerProvider.notifier)
          .addFromImageSelection(selection);
      if (mounted) {
        showValidation(
          context,
          'Added ${selection.selectedIngredients.length} item(s) to inventory.',
        );
      }
    } on ApiFailure catch (error) {
      if (mounted) {
        showValidation(context, error.message);
      }
    }
  }

  void _setVisionSelectionForRecipes(List<String> selectedIngredients) {
    final deduped = <String>[];
    final seen = <String>{};
    for (final ingredient in selectedIngredients) {
      final cleaned = ingredient.trim();
      if (cleaned.isEmpty) {
        continue;
      }
      final key = cleaned.toLowerCase();
      if (seen.contains(key)) {
        continue;
      }
      seen.add(key);
      deduped.add(cleaned);
    }
    ref.read(selectedVisionIngredientsProvider.notifier).state = deduped;
  }

  void _scrollToScanResult() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }

      final context = _scanResultKey.currentContext;
      if (context != null) {
        Scrollable.ensureVisible(
          context,
          duration: const Duration(milliseconds: 350),
          curve: Curves.easeOutCubic,
          alignment: 0.06,
        );
        return;
      }

      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 350),
          curve: Curves.easeOutCubic,
        );
      }
    });
  }
}

class BarcodeScannerScreen extends ConsumerWidget {
  const BarcodeScannerScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      appBar: AppBar(title: const Text('Barcode scanner')),
      body: Semantics(
        label: 'Barcode scanner camera preview',
        child: MobileScanner(
          onDetect: (capture) {
            final value = capture.barcodes
                .map((barcode) => barcode.rawValue)
                .whereType<String>()
                .firstOrNull;
            if (value == null || !RegExp(r'^[0-9]{8,14}$').hasMatch(value)) {
              return;
            }
            ref
                .read(scanControllerProvider.notifier)
                .run(
                  (client) => client.post(
                    '/v1/barcode/lookup',
                    {'barcode': value},
                    requiredFields: [
                      'product_id',
                      'name',
                      'nutrition',
                      'source',
                    ],
                  ),
                );
            context.go('/scan');
          },
        ),
      ),
    );
  }
}

class RecipesScreen extends ConsumerStatefulWidget {
  const RecipesScreen({super.key});

  @override
  ConsumerState<RecipesScreen> createState() => _RecipesScreenState();
}

class _RecipesScreenState extends ConsumerState<RecipesScreen> {
  final pantryController = TextEditingController();
  final manualInventoryController = TextEditingController();
  final recipeIdController = TextEditingController(text: 'recipe_stub_001');
  final questionController = TextEditingController(
    text: 'How do I make this recipe step by step?',
  );
  final Set<int> selectedInventoryItemIds = <int>{};
  final List<RecipeChatTurn> recipeChatTranscript = <RecipeChatTurn>[];
  RecipeSuggestionRecord? selectedRecipe;
  String budgetLevel = 'mid';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      unawaited(_refreshInventory());
    });
  }

  @override
  void dispose() {
    pantryController.dispose();
    manualInventoryController.dispose();
    recipeIdController.dispose();
    questionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final inventoryState = ref.watch(inventoryControllerProvider);
    final inventoryItems =
        inventoryState.valueOrNull ?? const <InventoryItemRecord>[];
    final inventoryLoading = inventoryState.isLoading;
    final inventoryError = inventoryState.error;
    final recipeState = ref.watch(recipeControllerProvider);
    final discussionState = ref.watch(recipeDiscussControllerProvider);
    final recipeSuggestions = recipeSuggestionsFromPayload(
      recipeState?.valueOrNull?.raw,
    );
    final selectedVisionIngredients = ref.watch(
      selectedVisionIngredientsProvider,
    );
    final selectedImageInventoryIngredients =
        _selectedImageInventoryIngredients(inventoryItems);
    final effectiveImageIngredients = _mergeImageIngredients(
      selectedVisionIngredients,
      selectedImageInventoryIngredients,
    );

    return EndpointPage(
      title: 'Recipes',
      children: [
        InputCard(
          title: 'Inventory',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      'Select items to use for recipe generation.',
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ),
                  IconButton(
                    tooltip: 'Refresh inventory',
                    onPressed: inventoryLoading ? null : _refreshInventory,
                    icon: const Icon(Icons.refresh),
                  ),
                ],
              ),
              TextFormField(
                controller: manualInventoryController,
                decoration: const InputDecoration(
                  labelText: 'Add inventory items',
                  helperText: 'Comma-separated, for example: rice, lentils',
                ),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  FilledButton.icon(
                    onPressed: _addManualInventoryItems,
                    icon: const Icon(Icons.add),
                    label: const Text('Add'),
                  ),
                  OutlinedButton.icon(
                    onPressed: inventoryItems.isEmpty
                        ? null
                        : _confirmClearInventory,
                    icon: const Icon(Icons.delete_sweep_outlined),
                    label: const Text('Clear inventory'),
                  ),
                ],
              ),
              if (inventoryLoading) ...[
                const SizedBox(height: 8),
                const LinearProgressIndicator(),
              ],
              if (inventoryError != null) ...[
                const SizedBox(height: 8),
                Text(
                  inventoryError is ApiFailure
                      ? inventoryError.message
                      : inventoryError.toString(),
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ],
              const SizedBox(height: 8),
              if (inventoryItems.isEmpty)
                Text(
                  'No inventory items yet.',
                  style: Theme.of(context).textTheme.bodyMedium,
                )
              else
                Column(
                  children: [
                    for (final item in inventoryItems)
                      Row(
                        children: [
                          Checkbox(
                            value: selectedInventoryItemIds.contains(item.id),
                            onChanged: (value) {
                              setState(() {
                                if (value == true) {
                                  selectedInventoryItemIds.add(item.id);
                                } else {
                                  selectedInventoryItemIds.remove(item.id);
                                }
                              });
                            },
                          ),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(item.name),
                                Text(
                                  'Source: ${item.sourceMethod}',
                                  style: Theme.of(context).textTheme.bodySmall,
                                ),
                              ],
                            ),
                          ),
                          IconButton(
                            tooltip: 'Remove item',
                            onPressed: () => _removeInventoryItem(item),
                            icon: const Icon(Icons.delete_outline),
                          ),
                        ],
                      ),
                  ],
                ),
            ],
          ),
        ),
        InputCard(
          title: 'Recipe suggestions',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                controller: pantryController,
                decoration: const InputDecoration(
                  labelText: 'Pantry items',
                  helperText: 'Comma-separated',
                ),
              ),
              DropdownButtonFormField<String>(
                initialValue: budgetLevel,
                decoration: const InputDecoration(labelText: 'Budget level'),
                items: const [
                  DropdownMenuItem(value: 'low', child: Text('Low')),
                  DropdownMenuItem(value: 'mid', child: Text('Medium')),
                  DropdownMenuItem(value: 'high', child: Text('High')),
                ],
                onChanged: (value) {
                  if (value == null) {
                    return;
                  }
                  setState(() => budgetLevel = value);
                },
              ),
              const SizedBox(height: 8),
              if (effectiveImageIngredients.isEmpty)
                Text(
                  'No selected image ingredients yet.',
                  style: Theme.of(context).textTheme.bodySmall,
                )
              else
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Using ${effectiveImageIngredients.length} selected image ingredient(s).',
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        for (final item in effectiveImageIngredients)
                          InputChip(
                            label: Text(item),
                            onDeleted: selectedVisionIngredients.contains(item)
                                ? () {
                                    final next = List<String>.from(
                                      selectedVisionIngredients,
                                    )..remove(item);
                                    ref
                                            .read(
                                              selectedVisionIngredientsProvider
                                                  .notifier,
                                            )
                                            .state =
                                        next;
                                  }
                                : null,
                          ),
                      ],
                    ),
                  ],
                ),
              if (selectedVisionIngredients.isNotEmpty) ...[
                const SizedBox(height: 6),
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: () {
                      ref
                              .read(selectedVisionIngredientsProvider.notifier)
                              .state =
                          const <String>[];
                    },
                    icon: const Icon(Icons.clear_all_outlined),
                    label: const Text('Clear image ingredients'),
                  ),
                ),
              ],
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: () => unawaited(_suggest()),
                icon: const Icon(Icons.restaurant_menu_outlined),
                label: const Text('Suggest recipes'),
              ),
            ],
          ),
        ),
        AsyncPayloadView(
          title: 'Recipe suggestions',
          value: recipeState,
          onRetry: () => unawaited(_suggest()),
        ),
        RecipeSuggestionPicker(
          recipes: recipeSuggestions,
          selectedRecipeId: selectedRecipe?.recipeId,
          onSelected: _selectRecipeSuggestion,
        ),
        InputCard(
          title: 'Recipe chatbot',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (selectedRecipe != null) ...[
                Row(
                  children: [
                    const Icon(Icons.restaurant_menu_outlined),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        selectedRecipe!.title,
                        style: Theme.of(context).textTheme.titleSmall,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Text(
                  selectedRecipe!.summary,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
              ],
              RecipeChatTranscriptView(turns: recipeChatTranscript),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  ActionChip(
                    avatar: const Icon(Icons.format_list_numbered, size: 18),
                    label: const Text('Step by step'),
                    onPressed: () =>
                        _setQuestion('How do I make this recipe step by step?'),
                  ),
                  ActionChip(
                    avatar: const Icon(Icons.swap_horiz, size: 18),
                    label: const Text('Substitutions'),
                    onPressed: () => _setQuestion(
                      'What can I substitute for the missing ingredients?',
                    ),
                  ),
                  ActionChip(
                    avatar: const Icon(Icons.kitchen_outlined, size: 18),
                    label: const Text('Use my ingredients'),
                    onPressed: () => _setQuestion(
                      'How should I use the ingredients I already have?',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: recipeIdController,
                decoration: const InputDecoration(labelText: 'Recipe id'),
              ),
              TextFormField(
                controller: questionController,
                decoration: const InputDecoration(labelText: 'Question'),
                minLines: 2,
                maxLines: 4,
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: () => unawaited(_discuss()),
                icon: const Icon(Icons.forum_outlined),
                label: const Text('Discuss recipe'),
              ),
            ],
          ),
        ),
        AsyncPayloadView(
          title: 'Recipe discussion',
          value: discussionState,
          onRetry: () => unawaited(_discuss()),
        ),
      ],
    );
  }

  List<String> _items() => pantryController.text
      .split(',')
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toList();

  Future<void> _refreshInventory() async {
    try {
      await ref.read(inventoryControllerProvider.notifier).refresh();
    } on ApiFailure catch (error) {
      if (mounted) {
        showValidation(context, error.message);
      }
    }
  }

  Future<void> _addManualInventoryItems() async {
    final body = buildInventoryManualAddBody(
      manualInventoryController.text.split(','),
    );
    final items = (body['items'] as List<Object?>).cast<String>();
    if (items.isEmpty) {
      showValidation(context, 'Enter at least one inventory item.');
      return;
    }
    try {
      await ref
          .read(inventoryControllerProvider.notifier)
          .addManualItems(items);
      manualInventoryController.clear();
      if (mounted) {
        showValidation(context, 'Inventory updated.');
      }
    } on ApiFailure catch (error) {
      if (mounted) {
        showValidation(context, error.message);
      }
    }
  }

  Future<void> _removeInventoryItem(InventoryItemRecord item) async {
    try {
      await ref.read(inventoryControllerProvider.notifier).deleteItem(item.id);
      if (mounted) {
        setState(() => selectedInventoryItemIds.remove(item.id));
        showValidation(context, 'Removed ${item.name}.');
      }
    } on ApiFailure catch (error) {
      if (mounted) {
        showValidation(context, error.message);
      }
    }
  }

  Future<void> _confirmClearInventory() async {
    final shouldClear = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear inventory'),
        content: const Text(
          'This will remove all inventory items for your account.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Clear'),
          ),
        ],
      ),
    );
    if (shouldClear != true) {
      return;
    }

    try {
      final result = await ref
          .read(inventoryControllerProvider.notifier)
          .clearAll();
      if (!mounted) {
        return;
      }
      setState(selectedInventoryItemIds.clear);
      if (result.failedCount == 0) {
        showValidation(context, 'Inventory cleared.');
      } else {
        showValidation(
          context,
          'Cleared ${result.deletedCount} item(s); failed ${result.failedCount}.',
        );
      }
    } on ApiFailure catch (error) {
      if (mounted) {
        showValidation(context, error.message);
      }
    }
  }

  Future<void> _suggest() async {
    final pantryItems = _items();
    final availableItems =
        ref.read(inventoryControllerProvider).valueOrNull ??
        const <InventoryItemRecord>[];
    final availableIds = availableItems.map((item) => item.id).toSet();
    final selectedInventoryIds = selectedInventoryItemIds
        .where((id) => availableIds.contains(id))
        .toList();
    final recognizedIngredients = _mergeImageIngredients(
      ref.read(selectedVisionIngredientsProvider),
      _selectedImageInventoryIngredients(availableItems),
    );

    if (pantryItems.isEmpty &&
        selectedInventoryIds.isEmpty &&
        recognizedIngredients.isEmpty) {
      showValidation(
        context,
        'Select inventory items, image ingredients, or enter pantry items before suggesting recipes.',
      );
      return;
    }

    final body = buildRecipeSuggestRequestBody(
      budgetLevel: budgetLevel,
      inventoryItemIds: selectedInventoryIds,
      pantryItems: pantryItems,
      recognizedIngredients: recognizedIngredients,
    );
    final includeDebug = ref.read(debugModeProvider);
    final suggestPath = includeDebug
        ? '/v1/recipes/suggest?debug=true'
        : '/v1/recipes/suggest';

    final payload = await ref
        .read(recipeControllerProvider.notifier)
        .run(
          (client) => client.post(
            suggestPath,
            body,
            requiredFields: ['recipes'],
            timeout: ApiClient.recipeTimeout,
          ),
        );
    if (!mounted || payload == null) {
      return;
    }
    final suggestions = recipeSuggestionsFromPayload(payload.raw);
    if (suggestions.isNotEmpty) {
      _selectRecipeSuggestion(suggestions.first);
    }
  }

  List<String> _selectedImageInventoryIngredients(
    List<InventoryItemRecord> inventoryItems,
  ) {
    final selectedNames = <String>[];
    final seen = <String>{};
    for (final item in inventoryItems) {
      if (!selectedInventoryItemIds.contains(item.id)) {
        continue;
      }
      if (item.sourceMethod.toLowerCase() != 'image') {
        continue;
      }
      final cleaned = item.name.trim();
      if (cleaned.isEmpty) {
        continue;
      }
      final key = cleaned.toLowerCase();
      if (seen.contains(key)) {
        continue;
      }
      seen.add(key);
      selectedNames.add(cleaned);
    }
    return selectedNames;
  }

  List<String> _mergeImageIngredients(
    List<String> recognizedIngredients,
    List<String> imageInventoryIngredients,
  ) {
    final merged = <String>[];
    final seen = <String>{};
    for (final item in [
      ...recognizedIngredients,
      ...imageInventoryIngredients,
    ]) {
      final cleaned = item.trim();
      if (cleaned.isEmpty) {
        continue;
      }
      final key = cleaned.toLowerCase();
      if (seen.contains(key)) {
        continue;
      }
      seen.add(key);
      merged.add(cleaned);
    }
    return merged;
  }

  Future<void> _discuss() async {
    final question = questionController.text.trim();
    if (question.isEmpty) {
      showValidation(context, 'Question is required.');
      return;
    }
    final recipeForRequest = _selectedRecipeForDiscussion();
    final payload = await ref
        .read(recipeDiscussControllerProvider.notifier)
        .run(
          (client) => client.post(
            '/v1/recipes/discuss',
            buildRecipeDiscussRequestBody(
              recipeId: recipeIdController.text.trim().isEmpty
                  ? 'recipe_stub_001'
                  : recipeIdController.text.trim(),
              selectedRecipe: recipeForRequest,
              question: question,
              conversationHistory: recipeChatTranscript,
            ),
            requiredFields: ['answer', 'grounded_references', 'safety_flags'],
            timeout: ApiClient.recipeTimeout,
          ),
        );
    if (!mounted || payload == null) {
      return;
    }
    final answer = text(payload.raw['answer'], fallback: '').trim();
    if (answer.isEmpty) {
      return;
    }
    setState(() {
      recipeChatTranscript.add(RecipeChatTurn(role: 'user', content: question));
      recipeChatTranscript.add(
        RecipeChatTurn(role: 'assistant', content: answer),
      );
      questionController.clear();
    });
  }

  RecipeSuggestionRecord? _selectedRecipeForDiscussion() {
    final recipe = selectedRecipe;
    if (recipe == null) {
      return null;
    }
    final currentRecipeId = recipeIdController.text.trim();
    if (currentRecipeId.isEmpty || currentRecipeId == recipe.recipeId) {
      return recipe;
    }
    return null;
  }

  void _selectRecipeSuggestion(RecipeSuggestionRecord recipe) {
    ref.read(recipeDiscussControllerProvider.notifier).clear();
    setState(() {
      selectedRecipe = recipe;
      recipeIdController.text = recipe.recipeId;
      recipeChatTranscript.clear();
      questionController.text = 'How do I make this recipe step by step?';
      questionController.selection = TextSelection.collapsed(
        offset: questionController.text.length,
      );
    });
  }

  void _setQuestion(String value) {
    questionController.text = value;
    questionController.selection = TextSelection.collapsed(
      offset: value.length,
    );
  }
}

class RecipeSuggestionPicker extends StatelessWidget {
  const RecipeSuggestionPicker({
    super.key,
    required this.recipes,
    required this.selectedRecipeId,
    required this.onSelected,
  });

  final List<RecipeSuggestionRecord> recipes;
  final String? selectedRecipeId;
  final ValueChanged<RecipeSuggestionRecord> onSelected;

  @override
  Widget build(BuildContext context) {
    if (recipes.isEmpty) {
      return const SizedBox.shrink();
    }
    final colors = Theme.of(context).colorScheme;
    return InputCard(
      title: 'Selected suggested recipe',
      child: Column(
        children: [
          for (final recipe in recipes)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Material(
                color: recipe.recipeId == selectedRecipeId
                    ? colors.primaryContainer
                    : colors.surface,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(8),
                  side: BorderSide(
                    color: recipe.recipeId == selectedRecipeId
                        ? colors.primary
                        : colors.outlineVariant,
                  ),
                ),
                child: InkWell(
                  borderRadius: BorderRadius.circular(8),
                  onTap: () => onSelected(recipe),
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(
                      children: [
                        Icon(
                          recipe.recipeId == selectedRecipeId
                              ? Icons.check_circle
                              : Icons.circle_outlined,
                          color: recipe.recipeId == selectedRecipeId
                              ? colors.primary
                              : colors.onSurfaceVariant,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                recipe.title,
                                style: Theme.of(context).textTheme.titleSmall,
                              ),
                              const SizedBox(height: 2),
                              Text(
                                recipe.summary,
                                style: Theme.of(context).textTheme.bodySmall,
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class RecipeChatTranscriptView extends StatelessWidget {
  const RecipeChatTranscriptView({super.key, required this.turns});

  final List<RecipeChatTurn> turns;

  @override
  Widget build(BuildContext context) {
    if (turns.isEmpty) {
      return Text(
        'No recipe discussion yet.',
        style: Theme.of(context).textTheme.bodyMedium,
      );
    }
    final colors = Theme.of(context).colorScheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        for (final turn in turns)
          Align(
            alignment: turn.role == 'user'
                ? Alignment.centerRight
                : Alignment.centerLeft,
            child: Container(
              constraints: const BoxConstraints(maxWidth: 560),
              margin: const EdgeInsets.symmetric(vertical: 4),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: turn.role == 'user'
                    ? colors.primaryContainer
                    : colors.surfaceContainerHighest,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    turn.role == 'user' ? 'You' : 'Qima',
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: colors.onSurfaceVariant,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(turn.content),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  static const _sexOptions = ['male', 'female'];
  static const _activityOptions = [
    'sedentary',
    'lightly_active',
    'moderately_active',
    'very_active',
    'athlete',
  ];
  static const _goalOptions = [
    'lose_weight',
    'maintain_weight',
    'gain_weight',
    'build_muscle',
    'improve_general_health',
    'eat_high_protein',
    'eat_low_calorie',
    'eat_balanced',
    'reduce_sugar',
    'reduce_sodium',
    'reduce_saturated_fat',
    'increase_fiber',
  ];

  final ageController = TextEditingController();
  final heightController = TextEditingController();
  final weightController = TextEditingController();
  final allergensController = TextEditingController();
  final dietaryRestrictionsController = TextEditingController();
  final safetyScreening = defaultSafetyScreening();
  String sex = 'male';
  String activity = 'moderately_active';
  String goal = 'improve_general_health';
  bool agreementAccepted = false;
  bool profileLoaded = false;
  bool loadingProfile = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      ref.read(profileControllerProvider.notifier).clear();
      unawaited(_loadProfile());
    });
  }

  @override
  void dispose() {
    ageController.dispose();
    heightController.dispose();
    weightController.dispose();
    allergensController.dispose();
    dietaryRestrictionsController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final profileState = ref.watch(profileControllerProvider);
    final isBusy = loadingProfile || (profileState?.isLoading ?? false);
    final canEdit = !loadingProfile;
    return EndpointPage(
      title: 'Profile',
      children: [
        NoticeCard(
          icon: Icons.info_outline,
          title: 'Boundary',
          message:
              'Profile context supports generally healthy adult food guidance.',
        ),
        InputCard(
          title: 'Profile update',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (!profileLoaded && isBusy) ...[
                const LinearProgressIndicator(),
                const SizedBox(height: 12),
              ],
              TextFormField(
                controller: ageController,
                enabled: canEdit,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Age years'),
              ),
              TextFormField(
                controller: heightController,
                enabled: canEdit,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Height cm'),
              ),
              TextFormField(
                controller: weightController,
                enabled: canEdit,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Weight kg'),
              ),
              DropdownButtonFormField<String>(
                key: ValueKey('sex-$sex'),
                initialValue: sex,
                decoration: const InputDecoration(labelText: 'Sex'),
                items: options(_sexOptions),
                onChanged: canEdit
                    ? (value) => setState(() => sex = value ?? sex)
                    : null,
              ),
              DropdownButtonFormField<String>(
                key: ValueKey('activity-$activity'),
                initialValue: activity,
                decoration: const InputDecoration(labelText: 'Activity level'),
                items: options(_activityOptions),
                onChanged: canEdit
                    ? (value) => setState(() => activity = value ?? activity)
                    : null,
              ),
              DropdownButtonFormField<String>(
                key: ValueKey('goal-$goal'),
                initialValue: goal,
                decoration: const InputDecoration(labelText: 'Goal'),
                items: options(_goalOptions),
                onChanged: canEdit
                    ? (value) => setState(() => goal = value ?? goal)
                    : null,
              ),
              TextFormField(
                controller: allergensController,
                enabled: canEdit,
                decoration: const InputDecoration(
                  labelText: 'Allergens (comma-separated)',
                ),
              ),
              TextFormField(
                controller: dietaryRestrictionsController,
                enabled: canEdit,
                decoration: const InputDecoration(
                  labelText: 'Dietary restrictions (comma-separated)',
                ),
              ),
              const SizedBox(height: 16),
              SafetyScreeningSection(
                values: safetyScreening,
                onChanged: _setSafetyScreening,
              ),
              const SizedBox(height: 16),
              AgreementSection(
                accepted: agreementAccepted,
                onChanged: canEdit
                    ? (value) => setState(() => agreementAccepted = value)
                    : null,
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: canEdit ? _saveProfile : null,
                icon: const Icon(Icons.save_outlined),
                label: const Text('Save profile'),
              ),
            ],
          ),
        ),
        AsyncPayloadView(
          title: 'Current profile',
          value: profileState,
          onRetry: _loadProfile,
        ),
      ],
    );
  }

  Future<void> _loadProfile() async {
    if (mounted) {
      setState(() => loadingProfile = true);
    }
    try {
      final payload = await ref
          .read(profileControllerProvider.notifier)
          .run(
            (client) => client.get(
              '/v1/profile/me',
              requiredFields: [
                'user_id',
                'age',
                'sex',
                'height_cm',
                'weight_kg',
                'activity_level',
                'goal',
                'safety_screening',
                'agreement_accepted',
                'updated_at',
              ],
            ),
          )
          .timeout(ApiClient.requestTimeout + const Duration(seconds: 2));

      if (!mounted || payload == null) {
        return;
      }
      _applyProfile(payload.raw);
    } on TimeoutException {
      if (mounted) {
        showValidation(
          context,
          'Profile request timed out. Check that the backend is running.',
        );
      }
    } finally {
      if (mounted) {
        setState(() => loadingProfile = false);
      }
    }
  }

  void _applyProfile(Map<String, Object?> profile) {
    setState(() {
      ageController.text = inputNumberText(profile['age']);
      heightController.text = inputNumberText(profile['height_cm']);
      weightController.text = inputNumberText(profile['weight_kg']);
      allergensController.text = commaSeparatedText(profile['allergens']);
      dietaryRestrictionsController.text = commaSeparatedText(
        profile['dietary_restrictions'],
      );
      sex = optionFromProfile(profile['sex'], _sexOptions, fallback: sex);
      activity = optionFromProfile(
        profile['activity_level'],
        _activityOptions,
        fallback: activity,
      );
      goal = optionFromProfile(profile['goal'], _goalOptions, fallback: goal);
      applySafetyScreeningFromProfile(
        safetyScreening,
        profile['safety_screening'],
      );
      agreementAccepted = profile['agreement_accepted'] == true;
      profileLoaded = true;
    });
  }

  Map<String, Object?>? _profileBody() {
    final age = int.tryParse(ageController.text.trim());
    final height = double.tryParse(heightController.text.trim());
    final weight = double.tryParse(weightController.text.trim());
    if (age == null || age < 1 || height == null || weight == null) {
      showValidation(
        context,
        'Age must be valid, and height/weight must be valid numbers.',
      );
      return null;
    }
    if (!safetyScreeningCompleted(safetyScreening)) {
      showValidation(
        context,
        'Please complete the Safety Screening before continuing.',
      );
      return null;
    }
    if (!agreementAccepted) {
      showValidation(context, agreementValidationMessage);
      return null;
    }

    final allergens = allergensController.text
        .split(',')
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();
    final restrictions = dietaryRestrictionsController.text
        .split(',')
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();

    final body = <String, Object?>{
      'age': age,
      'sex': sex,
      'height_cm': height,
      'weight_kg': weight,
      'activity_level': activity,
      'goal': goal,
      'allergens': allergens,
      'dietary_restrictions': restrictions,
      'safety_screening': safetyScreeningBody(safetyScreening),
      'agreement_accepted': agreementAccepted,
    };
    return body;
  }

  Future<void> _saveProfile() async {
    final body = _profileBody();
    if (body == null) {
      return;
    }
    setState(() => loadingProfile = true);
    try {
      final payload = await ref
          .read(profileControllerProvider.notifier)
          .run(
            (client) => client.post(
              '/v1/profile/update',
              body,
              requiredFields: [
                'user_id',
                'goal',
                'safety_screening',
                'agreement_accepted',
                'updated_at',
              ],
            ),
          )
          .timeout(ApiClient.requestTimeout + const Duration(seconds: 2));
      if (!mounted || payload == null) {
        return;
      }
      _applyProfile(payload.raw);
      showValidation(context, 'Profile updated.');
    } on TimeoutException {
      if (mounted) {
        showValidation(context, 'Saving profile timed out. Please retry.');
      }
    } finally {
      if (mounted) {
        setState(() => loadingProfile = false);
      }
    }
  }

  void _setSafetyScreening(String key, bool value) {
    setState(() => updateSafetyScreening(safetyScreening, key, value));
  }
}

class PlanScreen extends ConsumerStatefulWidget {
  const PlanScreen({super.key});

  @override
  ConsumerState<PlanScreen> createState() => _PlanScreenState();
}

class _PlanScreenState extends ConsumerState<PlanScreen> {
  final dislikedFoodsController = TextEditingController();
  final mealsPerDayController = TextEditingController(text: '3');
  final planDaysController = TextEditingController(text: '7');
  String budgetLevel = 'mid';
  String? eligibilityChoice;
  bool planDisclaimerAccepted = false;
  bool loadingProfile = false;
  Map<String, Object?>? currentProfile;
  String? profileLoadError;

  bool get canGenerateNutritionPlan {
    return eligibilityChoice == planEligibilityHealthy &&
        planDisclaimerAccepted &&
        !loadingProfile;
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      unawaited(_loadProfile());
    });
  }

  @override
  void dispose() {
    dislikedFoodsController.dispose();
    mealsPerDayController.dispose();
    planDaysController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final canEditPlanInputs = !loadingProfile;
    return EndpointPage(
      title: 'Nutrition Plan',
      children: [
        InputCard(
          title: 'Before we create your plan',
          child: const Text(
            'Qima can create nutrition plans for generally healthy adults. Some cases need professional nutrition support instead.',
          ),
        ),
        PlanEligibilitySection(
          selectedValue: eligibilityChoice,
          onChanged: (value) => setState(() => eligibilityChoice = value),
        ),
        InputCard(
          title: 'Plan preferences',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (loadingProfile) ...[
                const LinearProgressIndicator(),
                const SizedBox(height: 12),
              ],
              if (profileLoadError != null) ...[
                Text(
                  profileLoadError!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: _loadProfile,
                  icon: const Icon(Icons.refresh),
                  label: const Text('Retry profile load'),
                ),
                const SizedBox(height: 8),
              ],
              DropdownButtonFormField<String>(
                initialValue: budgetLevel,
                decoration: const InputDecoration(labelText: 'Budget level'),
                items: options(['low', 'mid', 'high']),
                onChanged: canEditPlanInputs
                    ? (value) =>
                          setState(() => budgetLevel = value ?? budgetLevel)
                    : null,
              ),
              TextFormField(
                controller: dislikedFoodsController,
                enabled: canEditPlanInputs,
                decoration: const InputDecoration(
                  labelText: 'Disliked foods',
                  hintText: 'tuna, eggplant',
                ),
              ),
              TextFormField(
                controller: mealsPerDayController,
                enabled: canEditPlanInputs,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Meals per day'),
              ),
              TextFormField(
                controller: planDaysController,
                enabled: canEditPlanInputs,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Plan days'),
              ),
            ],
          ),
        ),
        PlanDisclaimerCard(
          accepted: planDisclaimerAccepted,
          onChanged: (value) => setState(() => planDisclaimerAccepted = value),
        ),
        GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: canGenerateNutritionPlan ? null : _showPlanGateMessage,
          child: FilledButton.icon(
            onPressed: canGenerateNutritionPlan ? _generate : null,
            icon: const Icon(Icons.event_note_outlined),
            label: const Text('Generate nutrition plan'),
          ),
        ),
        OutlinedButton.icon(
          onPressed: _generateRecipesInstead,
          icon: const Icon(Icons.restaurant_menu_outlined),
          label: const Text('Generate recipes instead'),
        ),
        AsyncPayloadView(
          title: 'Nutrition plan response',
          value: ref.watch(planControllerProvider),
          onRetry: _generate,
        ),
        const SizedBox(height: 72),
      ],
    );
  }

  Future<void> _loadProfile() async {
    setState(() {
      loadingProfile = true;
      profileLoadError = null;
    });
    try {
      final payload = await ref
          .read(apiClientProvider)
          .get(
            '/v1/profile/me',
            requiredFields: [
              'user_id',
              'age',
              'sex',
              'height_cm',
              'weight_kg',
              'activity_level',
              'goal',
            ],
          );
      if (!mounted) {
        return;
      }
      setState(() => currentProfile = payload.raw);
    } on ApiFailure catch (error) {
      if (!mounted) {
        return;
      }
      setState(() => profileLoadError = error.message);
    } finally {
      if (mounted) {
        setState(() => loadingProfile = false);
      }
    }
  }

  void _generate() {
    if (!_validatePlanGate()) {
      return;
    }
    final profile = _planProfileFromSavedProfile();
    if (profile == null) {
      showValidation(
        context,
        'Load or complete your profile before generating a plan.',
      );
      return;
    }
    final mealsPerDay = int.tryParse(mealsPerDayController.text.trim());
    final planDays = int.tryParse(planDaysController.text.trim());
    if (mealsPerDay == null || mealsPerDay < 1 || mealsPerDay > 6) {
      showValidation(context, 'Meals per day must be between 1 and 6.');
      return;
    }
    if (planDays == null || planDays < 1 || planDays > 14) {
      showValidation(context, 'Plan days must be between 1 and 14.');
      return;
    }
    final dislikedFoods = dislikedFoodsController.text
        .split(',')
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();
    final body = <String, Object?>{
      'profile': profile,
      'safety_checks': _safetyChecksBody(),
      'budget': {
        'max_total_cost': budgetLevel,
        'currency': 'EGP',
        'geography': 'Cairo',
      },
      'disliked_foods': dislikedFoods,
      'dietary_filters': [
        if (budgetLevel == 'low') 'budget_friendly',
        'egyptian_foods',
      ],
      'plan_preferences': {
        'meal_count': mealsPerDay,
        'meals_per_day': mealsPerDay,
        'plan_days': planDays,
        'include_snacks': mealsPerDay > 3,
        'time_horizon': planDays > 1 ? 'multi_day' : 'single_day',
      },
    };
    ref
        .read(planControllerProvider.notifier)
        .run(
          (client) => client.post(
            '/v1/plans/generate',
            body,
            timeout: ApiClient.planTimeout,
            requiredFields: [
              'plan_id',
              'support_status',
              'nutrition_targets',
              'meals',
              'source',
            ],
          ),
        );
  }

  bool _validatePlanGate() {
    if (eligibilityChoice == null) {
      showValidation(
        context,
        'Please choose whether Qima can create a nutrition plan for you.',
      );
      return false;
    }
    if (eligibilityChoice == planEligibilityRestricted) {
      showValidation(
        context,
        'Nutrition plans are only available for generally healthy adults. You can still generate recipes instead.',
      );
      return false;
    }
    if (!planDisclaimerAccepted) {
      showValidation(
        context,
        'You must agree to the Qima AI Nutrition Disclaimer before generating a nutrition plan.',
      );
      return false;
    }
    if (loadingProfile) {
      showValidation(
        context,
        'Profile is still loading. Please wait a moment.',
      );
      return false;
    }
    return true;
  }

  void _showPlanGateMessage() {
    _validatePlanGate();
  }

  void _generateRecipesInstead() {
    context.go('/recipes');
  }

  Map<String, Object?> _safetyChecksBody() {
    return {
      'pregnant': false,
      'breastfeeding': false,
      'eating_disorder_history': false,
      'under_18': false,
      'medical_condition_affects_diet': false,
      'abnormal_labs_or_health_concerns': false,
      'none_of_above': true,
    };
  }

  Map<String, Object?>? _planProfileFromSavedProfile() {
    final profile = currentProfile;
    if (profile == null) {
      return null;
    }
    final age = number(profile['age'])?.round();
    final height = number(profile['height_cm']);
    final weight = number(profile['weight_kg']);
    if (age == null || age < 18 || height == null || weight == null) {
      return null;
    }
    return {
      'age_years': age,
      'sex': optionFromProfile(profile['sex'], [
        'male',
        'female',
        'other',
        'prefer_not_to_say',
      ], fallback: 'prefer_not_to_say'),
      'height_cm': height,
      'weight_kg': weight,
      'activity_level': optionFromProfile(profile['activity_level'], [
        'sedentary',
        'lightly_active',
        'moderately_active',
        'very_active',
        'athlete',
      ], fallback: 'moderately_active'),
      'goal': _planGoal(profile['goal']),
      'allergens': _planAllergens(profile['allergens']),
      'dietary_exclusions': _planDietaryExclusions(
        profile['dietary_restrictions'],
      ),
      'exclusion_flags': <String>[],
    };
  }

  String _planGoal(Object? value) {
    switch (text(value, fallback: '').trim()) {
      case 'lose_weight':
      case 'eat_low_calorie':
        return 'lose_weight';
      case 'build_muscle':
      case 'eat_high_protein':
      case 'gain_weight':
        return 'gain_muscle';
      case 'maintain_weight':
        return 'maintain_weight';
      default:
        return 'improve_general_health';
    }
  }

  List<String> _planAllergens(Object? value) {
    if (value is! List) {
      return <String>[];
    }
    final mapped = <String>{};
    for (final item in value) {
      final normalized = text(item, fallback: '').trim().toLowerCase();
      switch (normalized) {
        case 'milk':
        case 'egg':
        case 'fish':
        case 'shellfish':
        case 'wheat':
        case 'soy':
        case 'sesame':
          mapped.add(normalized);
        case 'peanut':
        case 'peanuts':
          mapped.add('peanuts');
        case 'tree_nut':
        case 'tree_nuts':
        case 'nuts':
          mapped.add('tree_nuts');
      }
    }
    return mapped.toList();
  }

  List<String> _planDietaryExclusions(Object? value) {
    if (value is! List) {
      return <String>[];
    }
    final exclusions = <String>{};
    for (final item in value) {
      final normalized = text(item, fallback: '').trim().toLowerCase();
      switch (normalized) {
        case 'halal':
          exclusions.addAll(['pork', 'alcohol']);
        case 'vegetarian':
          exclusions.addAll(['meat', 'poultry', 'fish', 'shellfish']);
        case 'vegan':
          exclusions.addAll([
            'meat',
            'poultry',
            'fish',
            'shellfish',
            'dairy',
            'eggs',
          ]);
        case 'dairy_free':
          exclusions.add('dairy');
        case 'egg_free':
          exclusions.add('eggs');
        case 'gluten_free':
          exclusions.add('gluten');
        case 'low_sodium':
          exclusions.add('high_sodium');
      }
    }
    return exclusions.toList();
  }
}

class GuidanceScreen extends ConsumerStatefulWidget {
  const GuidanceScreen({super.key});

  @override
  ConsumerState<GuidanceScreen> createState() => _GuidanceScreenState();
}

class _GuidanceScreenState extends ConsumerState<GuidanceScreen> {
  final markerController = TextEditingController(text: 'ferritin');
  final valueController = TextEditingController(text: '60');

  @override
  void dispose() {
    markerController.dispose();
    valueController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return EndpointPage(
      title: 'Guidance',
      children: [
        NoticeCard(
          icon: Icons.medical_information_outlined,
          title: 'Lab guidance boundary',
          message: 'Non-diagnostic. Food guidance only.',
        ),
        InputCard(
          title: 'Lab marker interpretation',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                controller: markerController,
                decoration: const InputDecoration(labelText: 'Marker name'),
              ),
              TextFormField(
                controller: valueController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Value'),
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: _interpretLab,
                icon: const Icon(Icons.health_and_safety_outlined),
                label: const Text('Interpret lab marker'),
              ),
            ],
          ),
        ),
        InputCard(
          title: 'Lab report extraction',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Upload a lab report PDF or page images and let the backend extract structured lab results.',
              ),
              const SizedBox(height: 8),
              OutlinedButton.icon(
                onPressed: () => context.go('/labs/extract-report-test'),
                icon: const Icon(Icons.upload_file_outlined),
                label: const Text('Open extraction test'),
              ),
            ],
          ),
        ),
        AsyncPayloadView(
          title: 'Lab response',
          value: ref.watch(labsControllerProvider),
          onRetry: _interpretLab,
        ),
      ],
    );
  }

  void _interpretLab() {
    final marker = markerController.text.trim();
    final value = double.tryParse(valueController.text.trim());
    if (marker.isEmpty || value == null) {
      showValidation(context, 'Marker and numeric value are required.');
      return;
    }
    ref
        .read(labsControllerProvider.notifier)
        .run(
          (client) => client.post(
            '/v1/labs/interpret',
            {
              'marker_name': marker,
              'value': value,
              'unit': 'ng/ml',
              'reference_range': {'low': 30, 'high': 300, 'unit': 'ng/ml'},
            },
            requiredFields: ['marker', 'support_status', 'safety_flags'],
          ),
        );
  }
}

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final questionController = TextEditingController(
    text: 'Can you recommend a more price friendly recipe?',
  );
  final budgetController = TextEditingController(text: '60');
  final geographyController = TextEditingController(text: 'Cairo');

  @override
  void dispose() {
    questionController.dispose();
    budgetController.dispose();
    geographyController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return EndpointPage(
      title: 'Chat',
      children: [
        InputCard(
          title: 'Grounded question',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                controller: questionController,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(labelText: 'Question'),
              ),
              TextFormField(
                controller: budgetController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Budget context EGP',
                ),
              ),
              TextFormField(
                controller: geographyController,
                decoration: const InputDecoration(labelText: 'Price geography'),
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: _ask,
                icon: const Icon(Icons.send_outlined),
                label: const Text('Ask'),
              ),
            ],
          ),
        ),
        AsyncPayloadView(
          title: 'Chat response',
          value: ref.watch(chatControllerProvider),
          onRetry: _ask,
        ),
      ],
    );
  }

  void _ask() {
    final question = questionController.text.trim();
    final budget = double.tryParse(budgetController.text.trim());
    final geography = geographyController.text.trim();
    if (question.isEmpty) {
      showValidation(context, 'Question is required.');
      return;
    }
    if (budgetController.text.trim().isNotEmpty && budget == null) {
      showValidation(context, 'Budget context must be a number.');
      return;
    }
    ref
        .read(chatControllerProvider.notifier)
        .run(
          (client) => client.post(
            '/v1/chat/query',
            {
              'context_id': 'ctx_stub_001',
              'active_context_type': 'recipe_suggestions',
              'question': question,
              'food_context': {
                'budget': priceBudgetContext(
                  maxTotalCost: budget,
                  geography: geography,
                ),
                'recipes':
                    ref
                        .read(recipeControllerProvider)
                        ?.valueOrNull
                        ?.raw['recipes'] ??
                    <Object?>[],
                'estimated_costs': _estimatedCostsFromLatestRecipes(),
              },
            },
            requiredFields: ['answer', 'source_references', 'safety_flags'],
          ),
        );
  }

  List<Object?> _estimatedCostsFromLatestRecipes() {
    final recipes = ref
        .read(recipeControllerProvider)
        ?.valueOrNull
        ?.raw['recipes'];
    if (recipes is! List) {
      return <Object?>[];
    }
    return [
      for (final recipe in recipes)
        if (recipe is Map && recipe['estimated_cost'] != null)
          {
            'recipe_id': recipe['recipe_id'],
            'title': recipe['title'],
            'estimated_cost': recipe['estimated_cost'],
          },
    ];
  }
}

class DebugScreen extends ConsumerWidget {
  const DebugScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final health = ref.watch(healthProvider);
    final debug = ref.watch(debugModeProvider);
    return EndpointPage(
      title: 'Debug and health',
      children: [
        SwitchListTile(
          title: const Text('Show debug payloads'),
          subtitle: const Text('Shows raw responses and latency fields.'),
          value: debug,
          onChanged: (value) =>
              ref.read(debugModeProvider.notifier).state = value,
        ),
        Text('API base URL: $apiBaseUrl'),
        const SizedBox(height: 8),
        OutlinedButton.icon(
          onPressed: () => context.go('/labs/extract-report-test'),
          icon: const Icon(Icons.science_outlined),
          label: const Text('Lab report extraction test'),
        ),
        AsyncPayloadView(
          title: 'Backend health',
          value: health,
          onRetry: () => ref.invalidate(healthProvider),
        ),
      ],
    );
  }
}

class EndpointPage extends StatelessWidget {
  const EndpointPage({
    super.key,
    required this.title,
    required this.children,
    this.scrollController,
  });

  final String title;
  final List<Widget> children;
  final ScrollController? scrollController;

  @override
  Widget build(BuildContext context) {
    return ListView(
      controller: scrollController,
      padding: const EdgeInsets.all(16),
      children: [
        Text(title, style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 8),
        ...children,
      ],
    );
  }
}

class InputCard extends StatelessWidget {
  const InputCard({super.key, required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            child,
          ],
        ),
      ),
    );
  }
}

class AsyncPayloadView extends ConsumerWidget {
  const AsyncPayloadView({
    super.key,
    required this.title,
    required this.value,
    required this.onRetry,
    this.onEstimateNutritionFromVision,
    this.onAddBarcodeToInventory,
    this.onAddInventoryFromVision,
    this.onVisionSelectionChanged,
  });

  final String title;
  final AsyncValue<ApiPayload>? value;
  final VoidCallback onRetry;
  final ValueChanged<Map<String, Object?>>? onEstimateNutritionFromVision;
  final Future<void> Function(Map<String, Object?> raw)?
  onAddBarcodeToInventory;
  final Future<void> Function(InventoryImageSelection selection)?
  onAddInventoryFromVision;
  final ValueChanged<List<String>>? onVisionSelectionChanged;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final current = value;
    if (current == null) {
      return EmptyState(title: title);
    }
    return current.when(
      data: (payload) => PayloadCard(
        title: title,
        payload: payload,
        onEstimateNutritionFromVision: onEstimateNutritionFromVision,
        onAddBarcodeToInventory: onAddBarcodeToInventory,
        onAddInventoryFromVision: onAddInventoryFromVision,
        onVisionSelectionChanged: onVisionSelectionChanged,
      ),
      error: (error, stackTrace) {
        final failure = error is ApiFailure
            ? error
            : ApiFailure(message: error.toString(), retryable: false);
        return ErrorState(title: title, failure: failure, onRetry: onRetry);
      },
      loading: () => LoadingState(title: title),
    );
  }
}

class LoadingState extends StatelessWidget {
  const LoadingState({super.key, required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: const SizedBox.square(
          dimension: 24,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
        title: Text(title),
        subtitle: const Text('Calling FastAPI...'),
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: const Icon(Icons.inbox_outlined),
        title: Text(title),
        subtitle: const Text('No response yet.'),
      ),
    );
  }
}

class ErrorState extends StatelessWidget {
  const ErrorState({
    super.key,
    required this.title,
    required this.failure,
    required this.onRetry,
  });

  final String title;
  final ApiFailure failure;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.error_outline, color: Colors.red),
                const SizedBox(width: 8),
                Expanded(child: Text(title)),
              ],
            ),
            const SizedBox(height: 8),
            Text(failure.message),
            if (failure.statusCode != null) Text('HTTP ${failure.statusCode}'),
            if (failure.retryable) ...[
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class PayloadCard extends ConsumerWidget {
  const PayloadCard({
    super.key,
    required this.title,
    required this.payload,
    this.onEstimateNutritionFromVision,
    this.onAddBarcodeToInventory,
    this.onAddInventoryFromVision,
    this.onVisionSelectionChanged,
  });

  final String title;
  final ApiPayload payload;
  final ValueChanged<Map<String, Object?>>? onEstimateNutritionFromVision;
  final Future<void> Function(Map<String, Object?> raw)?
  onAddBarcodeToInventory;
  final Future<void> Function(InventoryImageSelection selection)?
  onAddInventoryFromVision;
  final ValueChanged<List<String>>? onVisionSelectionChanged;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final debug = ref.watch(debugModeProvider);
    final raw = payload.raw;
    final summary = summarizePayload(raw);
    final isBarcodeScan = isBarcodeScanPayload(raw);
    final isVisionIdentify = isVisionIdentifyPayload(raw);
    final isNutritionEstimate = isNutritionEstimatePayload(raw);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            if (payload.hasContractIssues)
              NoticeCard(
                icon: Icons.rule_folder_outlined,
                title: 'Contract validation',
                message: payload.contractIssues.join('\n'),
              ),
            if (payload.isPartial)
              NoticeCard(
                icon: Icons.warning_amber_outlined,
                title: 'Uncertainty',
                message: payload.partialReasons.join('\n'),
              ),
            if (isBarcodeScan)
              BarcodeScanResultView(
                raw: raw,
                onAddToInventory: onAddBarcodeToInventory,
              )
            else if (isVisionIdentify)
              VisionIdentifyResultView(
                raw: raw,
                onEstimateNutrition: onEstimateNutritionFromVision,
                onAddToInventory: onAddInventoryFromVision,
                onSelectionChanged: onVisionSelectionChanged,
              )
            else if (isNutritionEstimate)
              NutritionEstimateResultView(raw: raw)
            else
              for (final item in summary.entries)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: RichText(
                    text: TextSpan(
                      style: Theme.of(context).textTheme.bodyMedium,
                      children: [
                        TextSpan(
                          text: '${item.key}: ',
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        TextSpan(text: item.value),
                      ],
                    ),
                  ),
                ),
            const SizedBox(height: 8),
            SourceMetadata(raw: raw),
            if (debug) DebugPayload(raw: raw),
          ],
        ),
      ),
    );
  }
}

class BarcodeScanResultView extends StatelessWidget {
  const BarcodeScanResultView({
    super.key,
    required this.raw,
    this.onAddToInventory,
  });

  final Map<String, Object?> raw;
  final Future<void> Function(Map<String, Object?> raw)? onAddToInventory;

  @override
  Widget build(BuildContext context) {
    final productName = text(raw['name'], fallback: 'Unknown product').trim();
    final brand = text(raw['brand'], fallback: '').trim();
    final nutrition = raw['nutrition'];
    final basis = nutritionBasisDisplayLabel(nutrition);
    final nutrients = nutritionRows(nutrition);
    final ingredients = ingredientsParagraph(raw['ingredients']);
    final allergens = allergensBySeverity(raw['allergens']);
    final contains = allergens['contains'] ?? const <String>[];
    final mayContain = allergens['may_contain'] ?? const <String>[];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          productName,
          style: Theme.of(
            context,
          ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
        ),
        if (brand.isNotEmpty) ...[
          const SizedBox(height: 2),
          Text(
            'Brand: $brand',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ],
        const SizedBox(height: 12),
        SectionHeader(title: 'Nutrition - $basis'),
        const SizedBox(height: 6),
        if (nutrients.isEmpty)
          Text(
            'Unavailable',
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: Colors.grey.shade700),
          )
        else
          Column(
            children: [
              for (final row in nutrients)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          row.label,
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Text(
                        row.value,
                        textAlign: TextAlign.right,
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        const SizedBox(height: 12),
        const SectionHeader(title: 'Ingredients'),
        const SizedBox(height: 6),
        Text(ingredients, style: Theme.of(context).textTheme.bodyMedium),
        const SizedBox(height: 12),
        if (onAddToInventory != null)
          FilledButton.icon(
            onPressed: () => onAddToInventory!(raw),
            icon: const Icon(Icons.inventory_2_outlined),
            label: const Text('Add to inventory'),
          ),
        if (onAddToInventory != null) const SizedBox(height: 12),
        const SectionHeader(title: 'Allergens'),
        const SizedBox(height: 6),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: Theme.of(
              context,
            ).colorScheme.errorContainer.withValues(alpha: 0.35),
            border: Border.all(color: Theme.of(context).colorScheme.error),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (contains.isEmpty && mayContain.isEmpty)
                Text(
                  'Contains: None declared',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              if (contains.isNotEmpty) ...[
                Text(
                  'Contains:',
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final allergen in contains)
                      Chip(
                        label: Text(allergen),
                        visualDensity: VisualDensity.compact,
                      ),
                  ],
                ),
              ],
              if (mayContain.isNotEmpty) ...[
                if (contains.isNotEmpty) const SizedBox(height: 8),
                Text(
                  'May contain:',
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 6),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final allergen in mayContain)
                      Chip(
                        label: Text(allergen),
                        visualDensity: VisualDensity.compact,
                      ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class VisionIdentifyResultView extends StatefulWidget {
  const VisionIdentifyResultView({
    super.key,
    required this.raw,
    this.onEstimateNutrition,
    this.onAddToInventory,
    this.onSelectionChanged,
  });

  final Map<String, Object?> raw;
  final ValueChanged<Map<String, Object?>>? onEstimateNutrition;
  final Future<void> Function(InventoryImageSelection selection)?
  onAddToInventory;
  final ValueChanged<List<String>>? onSelectionChanged;

  @override
  State<VisionIdentifyResultView> createState() =>
      _VisionIdentifyResultViewState();
}

class _VisionIdentifyResultViewState extends State<VisionIdentifyResultView> {
  Set<String> _selectedIngredientKeys = <String>{};
  bool _submittingInventory = false;
  bool _selectionNotificationScheduled = false;

  @override
  void initState() {
    super.initState();
    _resetSelection();
  }

  @override
  void didUpdateWidget(covariant VisionIdentifyResultView oldWidget) {
    super.didUpdateWidget(oldWidget);
    final previousImageId = text(
      oldWidget.raw['image_id'],
      fallback: '',
    ).trim();
    final currentImageId = text(widget.raw['image_id'], fallback: '').trim();
    if (previousImageId != currentImageId ||
        !mapEquals(oldWidget.raw, widget.raw)) {
      _resetSelection();
    }
  }

  void _resetSelection() {
    final recognized = _recognizedIngredientNames();
    _selectedIngredientKeys = {
      for (final name in recognized) _normalizedVisionName(name),
    };
    _scheduleSelectionChangedNotification();
  }

  List<String> _recognizedIngredientNames() {
    final candidates = visionCandidates(widget.raw['ingredients']);
    final names = <String>[];
    final seen = <String>{};
    for (final candidate in candidates) {
      final cleaned = candidate.name.trim();
      if (cleaned.isEmpty) {
        continue;
      }
      final key = _normalizedVisionName(cleaned);
      if (key.isEmpty || seen.contains(key)) {
        continue;
      }
      seen.add(key);
      names.add(cleaned);
    }
    return names;
  }

  List<String> _selectedIngredientNames() {
    final selected = <String>[];
    for (final ingredient in _recognizedIngredientNames()) {
      if (_selectedIngredientKeys.contains(_normalizedVisionName(ingredient))) {
        selected.add(ingredient);
      }
    }
    return selected;
  }

  void _notifySelectionChanged() {
    widget.onSelectionChanged?.call(_selectedIngredientNames());
  }

  void _scheduleSelectionChangedNotification() {
    if (_selectionNotificationScheduled) {
      return;
    }
    _selectionNotificationScheduled = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _selectionNotificationScheduled = false;
      if (!mounted) {
        return;
      }
      _notifySelectionChanged();
    });
  }

  @override
  Widget build(BuildContext context) {
    final raw = widget.raw;
    final dishCandidates = visionCandidates(raw['dish_candidates']);
    final ingredientCandidates = visionCandidates(raw['ingredients']);
    final topCandidate = dishCandidates.isEmpty ? null : dishCandidates.first;
    final confidence = number(raw['confidence']);
    final warnings = textList(raw['warnings']);
    final recognizedNames = _recognizedIngredientNames();
    final candidateByKey = <String, VisionCandidate>{};
    for (final candidate in ingredientCandidates) {
      final key = _normalizedVisionName(candidate.name);
      candidateByKey.putIfAbsent(key, () => candidate);
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          topCandidate?.name ?? 'Unknown food item',
          style: Theme.of(
            context,
          ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
        ),
        if (confidence != null) ...[
          const SizedBox(height: 2),
          Text(
            'Overall confidence: ${formatConfidence(confidence)}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ],
        const SizedBox(height: 12),
        const SectionHeader(title: 'Dish candidates'),
        const SizedBox(height: 6),
        if (dishCandidates.isEmpty)
          Text(
            'No reliable dish candidates returned.',
            style: Theme.of(context).textTheme.bodyMedium,
          )
        else
          Column(
            children: [
              for (final candidate in dishCandidates)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          candidate.name,
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                      ),
                      if (candidate.confidence != null) ...[
                        const SizedBox(width: 12),
                        Text(
                          formatConfidence(candidate.confidence!),
                          textAlign: TextAlign.right,
                          style: Theme.of(context).textTheme.bodyMedium
                              ?.copyWith(fontWeight: FontWeight.w600),
                        ),
                      ],
                    ],
                  ),
                ),
            ],
          ),
        const SizedBox(height: 12),
        const SectionHeader(title: 'Ingredients'),
        const SizedBox(height: 6),
        if (ingredientCandidates.isEmpty)
          Text(
            'No reliable ingredient candidates returned.',
            style: Theme.of(context).textTheme.bodyMedium,
          )
        else
          Column(
            children: [
              for (final ingredientName in recognizedNames)
                CheckboxListTile(
                  value: _selectedIngredientKeys.contains(
                    _normalizedVisionName(ingredientName),
                  ),
                  contentPadding: EdgeInsets.zero,
                  controlAffinity: ListTileControlAffinity.leading,
                  title: Text(ingredientName),
                  subtitle: Builder(
                    builder: (_) {
                      final candidate =
                          candidateByKey[_normalizedVisionName(ingredientName)];
                      if (candidate == null || candidate.confidence == null) {
                        return const SizedBox.shrink();
                      }
                      return Text(formatConfidence(candidate.confidence!));
                    },
                  ),
                  onChanged: (selected) {
                    setState(() {
                      final key = _normalizedVisionName(ingredientName);
                      if (selected == true) {
                        _selectedIngredientKeys.add(key);
                      } else {
                        _selectedIngredientKeys.remove(key);
                      }
                    });
                    _notifySelectionChanged();
                  },
                ),
            ],
          ),
        if (widget.onAddToInventory != null) ...[
          const SizedBox(height: 8),
          FilledButton.icon(
            onPressed: _submittingInventory
                ? null
                : () async {
                    final imageId = text(raw['image_id'], fallback: '').trim();
                    if (imageId.isEmpty) {
                      showValidation(
                        context,
                        'Could not determine image id for inventory submission.',
                      );
                      return;
                    }

                    final selectedIngredients = [
                      for (final name in recognizedNames)
                        if (_selectedIngredientKeys.contains(
                          _normalizedVisionName(name),
                        ))
                          name,
                    ];
                    if (selectedIngredients.isEmpty) {
                      showValidation(
                        context,
                        'Select at least one ingredient to add.',
                      );
                      return;
                    }

                    final selection = InventoryImageSelection(
                      imageId: imageId,
                      recognizedIngredients: recognizedNames,
                      selectedIngredients: selectedIngredients,
                    );
                    setState(() => _submittingInventory = true);
                    try {
                      await widget.onAddToInventory!(selection);
                    } finally {
                      if (mounted) {
                        setState(() => _submittingInventory = false);
                      }
                    }
                  },
            icon: const Icon(Icons.playlist_add_outlined),
            label: Text(
              _submittingInventory ? 'Adding...' : 'Add selected to inventory',
            ),
          ),
        ],
        if (widget.onEstimateNutrition != null) ...[
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: () => widget.onEstimateNutrition!(raw),
            icon: const Icon(Icons.calculate_outlined),
            label: const Text('Estimate nutrition'),
          ),
        ],
        if (warnings.isNotEmpty)
          NoticeCard(
            icon: Icons.warning_amber_outlined,
            title: 'Warnings',
            message: warnings.join('\n'),
          ),
      ],
    );
  }
}

class NutritionEstimateResultView extends StatelessWidget {
  const NutritionEstimateResultView({super.key, required this.raw});

  final Map<String, Object?> raw;

  @override
  Widget build(BuildContext context) {
    final matchedDish = raw['matched_dish'];
    final matchedName = matchedDish is Map
        ? text(matchedDish['name'], fallback: 'Estimated nutrition').trim()
        : 'Estimated nutrition';
    final matchType = matchedDish is Map
        ? text(matchedDish['match_type'], fallback: '').trim()
        : '';
    final servingAssumptions = raw['serving_assumptions'];
    final servingBasis = servingAssumptions is Map
        ? text(servingAssumptions['basis'], fallback: '').trim()
        : '';
    final servingNote = servingAssumptions is Map
        ? text(servingAssumptions['note'], fallback: '').trim()
        : '';
    final nutrients = nutritionEstimateRows(raw['nutrients']);
    final confidence = number(raw['confidence']);
    final warnings = textList(raw['warnings']);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          matchedName.isEmpty ? 'Estimated nutrition' : matchedName,
          style: Theme.of(
            context,
          ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
        ),
        if (matchType.isNotEmpty) ...[
          const SizedBox(height: 2),
          Text(
            'Match: ${matchType.replaceAll('_', ' ')}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ],
        if (confidence != null) ...[
          const SizedBox(height: 2),
          Text(
            'Estimate confidence: ${formatConfidence(confidence)}',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
            ),
          ),
        ],
        const SizedBox(height: 12),
        const SectionHeader(title: 'Estimated nutrition'),
        const SizedBox(height: 6),
        if (nutrients.isEmpty)
          Text('Unavailable', style: Theme.of(context).textTheme.bodyMedium)
        else
          Column(
            children: [
              for (final row in nutrients)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          row.label,
                          style: Theme.of(context).textTheme.bodyMedium,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Text(
                        row.value,
                        textAlign: TextAlign.right,
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        if (servingBasis.isNotEmpty || servingNote.isNotEmpty) ...[
          const SizedBox(height: 12),
          const SectionHeader(title: 'Serving assumption'),
          const SizedBox(height: 6),
          if (servingBasis.isNotEmpty)
            Text(servingBasis, style: Theme.of(context).textTheme.bodyMedium),
          if (servingNote.isNotEmpty) ...[
            const SizedBox(height: 2),
            Text(
              servingNote,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ],
        if (warnings.isNotEmpty)
          NoticeCard(
            icon: Icons.warning_amber_outlined,
            title: 'Warnings',
            message: warnings.join('\n'),
          ),
      ],
    );
  }
}

class SectionHeader extends StatelessWidget {
  const SectionHeader({super.key, required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Text(
      title,
      style: Theme.of(
        context,
      ).textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700),
    );
  }
}

class NoticeCard extends StatelessWidget {
  const NoticeCard({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
  });

  final IconData icon;
  final String title;
  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 6),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 4),
                Text(message),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

const safetyRestrictionMessage =
    'Qima can still provide general food information, but personalized meal plans may not be available for this profile because Qima is not a medical or clinical nutrition service.';

const agreementValidationMessage =
    'You must read and agree to the Qima AI Nutrition Disclaimer & User Agreement before continuing.';

const qimaAgreementText = '''
By using Qima, you acknowledge and agree to the following:

Qima is an AI-powered nutrition and grocery assistant. It provides estimated nutrition information, recipe suggestions, product comparisons, price-aware guidance, and general food-related recommendations based on available data sources, user inputs, and AI-generated analysis.

Qima is not a doctor, dietitian, nutritionist, pharmacist, or medical service. The information provided by Qima is for general informational and educational purposes only and must not be used as a substitute for professional medical, nutritional, or dietary advice.

Qima may use AI models and external data sources to generate responses. Because AI systems and food databases can be incomplete, outdated, inaccurate, or uncertain, Qima's outputs may contain errors. You must not rely on Qima as a 100% accurate source for medical decisions, diagnosis or treatment, allergy safety, pregnancy or breastfeeding nutrition, eating disorder support, clinical diet planning, lab test interpretation, emergency health decisions, exact calorie or nutrient values, or exact food prices.

Food labels, ingredient lists, allergen information, nutrition values, prices, and recipe data may be missing, outdated, or incorrect. Always verify product packaging, allergen labels, and medical concerns directly with trusted sources or qualified professionals.

If you have a medical condition, allergy, pregnancy, breastfeeding status, eating disorder history, abnormal lab results, or any health-related concern, you should consult a qualified healthcare professional before following any recommendation from Qima.

Qima may provide estimated calorie needs, meal plans, or food suggestions based on your profile information. These estimates are not personalized medical advice and may not be suitable for every person.

Qima does not guarantee that any suggested food, ingredient, recipe, or meal plan is safe, accurate, complete, affordable, available, or suitable for your needs.

By continuing, you confirm that:
- You understand Qima provides AI-generated informational guidance only.
- You understand Qima may be inaccurate or incomplete.
- You will verify important information yourself.
- You will not rely on Qima for medical, allergy, pregnancy, breastfeeding, eating disorder, or emergency decisions.
- You accept responsibility for your own food choices and health-related decisions.
''';

const planEligibilityHealthy = 'generally_healthy';
const planEligibilityRestricted = 'needs_professional_support';

class PlanEligibilitySection extends StatelessWidget {
  const PlanEligibilitySection({
    super.key,
    required this.selectedValue,
    required this.onChanged,
  });

  final String? selectedValue;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    final hasRestriction = selectedValue == planEligibilityRestricted;
    return InputCard(
      title: 'Choose one',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          PlanChoiceTile(
            title: 'I am generally healthy',
            description:
                'None of these apply to me: under 18, pregnant, breastfeeding, eating disorder history, medical condition affecting diet, or abnormal lab results/health concerns.',
            selected: selectedValue == planEligibilityHealthy,
            onTap: () => onChanged(planEligibilityHealthy),
          ),
          const SizedBox(height: 8),
          PlanChoiceTile(
            title: 'One of these applies to me',
            description:
                'Qima will not create a personalized nutrition plan for this profile, but you can still generate recipes and view general food information.',
            selected: hasRestriction,
            onTap: () => onChanged(planEligibilityRestricted),
          ),
          if (hasRestriction) ...[
            const SizedBox(height: 8),
            const NoticeCard(
              icon: Icons.info_outline,
              title: 'Nutrition plan unavailable',
              message:
                  'Personalized nutrition plans are not available for this profile. You can still generate recipes and view general food information.',
            ),
          ],
        ],
      ),
    );
  }
}

class PlanChoiceTile extends StatelessWidget {
  const PlanChoiceTile({
    super.key,
    required this.title,
    required this.description,
    required this.selected,
    required this.onTap,
  });

  final String title;
  final String description;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final borderColor = selected
        ? colorScheme.primary
        : colorScheme.outlineVariant;
    return Material(
      color: selected
          ? colorScheme.primaryContainer.withValues(alpha: 0.28)
          : colorScheme.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: borderColor),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                selected
                    ? Icons.radio_button_checked
                    : Icons.radio_button_unchecked,
                color: selected ? colorScheme.primary : colorScheme.outline,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      description,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class PlanDisclaimerCard extends StatelessWidget {
  const PlanDisclaimerCard({
    super.key,
    required this.accepted,
    required this.onChanged,
  });

  final bool accepted;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return InputCard(
      title: 'Qima AI Nutrition Disclaimer',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'Qima provides AI-generated nutrition guidance for informational purposes only. It may be inaccurate or incomplete and should not replace professional medical, dietary, or allergy advice.',
          ),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () => _showAgreement(context),
              child: const Text('Read full agreement'),
            ),
          ),
          CheckboxListTile(
            dense: true,
            visualDensity: VisualDensity.compact,
            contentPadding: EdgeInsets.zero,
            title: const Text(
              'I have read and agree to the Qima AI Nutrition Disclaimer & User Agreement.',
            ),
            value: accepted,
            onChanged: (value) => onChanged(value ?? false),
            controlAffinity: ListTileControlAffinity.leading,
          ),
        ],
      ),
    );
  }

  void _showAgreement(BuildContext context) {
    showDialog<void>(
      context: context,
      builder: (context) {
        return AlertDialog(
          title: const Text('Qima AI Nutrition Disclaimer & User Agreement'),
          content: const SizedBox(
            width: double.maxFinite,
            child: SingleChildScrollView(child: Text(qimaAgreementText)),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Close'),
            ),
          ],
        );
      },
    );
  }
}

class ProfileFormSection extends StatelessWidget {
  const ProfileFormSection({
    super.key,
    required this.title,
    required this.child,
  });

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            title,
            style: Theme.of(
              context,
            ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 8),
          child,
        ],
      ),
    );
  }
}

class SafetyScreeningSection extends StatelessWidget {
  const SafetyScreeningSection({
    super.key,
    required this.values,
    required this.onChanged,
  });

  final Map<String, bool> values;
  final void Function(String key, bool value) onChanged;

  @override
  Widget build(BuildContext context) {
    final hasRestriction = safetyScreeningHasRestriction(values);
    return ProfileFormSection(
      title: 'Safety Screening',
      child: Column(
        children: [
          _screeningTile('pregnant', 'I am pregnant'),
          _screeningTile('breastfeeding', 'I am breastfeeding'),
          _screeningTile(
            'eating_disorder_history',
            'I have or had an eating disorder',
          ),
          _screeningTile('under_18', 'I am under 18'),
          _screeningTile(
            'medical_condition_affects_diet',
            'I have a medical condition that affects my diet',
          ),
          _screeningTile(
            'abnormal_labs_or_health_concerns',
            'I have abnormal lab results or health concerns',
          ),
          const Divider(),
          _screeningTile('none_of_above', 'None of the above apply to me'),
          if (hasRestriction)
            const NoticeCard(
              icon: Icons.info_outline,
              title: 'Personalized planning may be limited',
              message: safetyRestrictionMessage,
            ),
        ],
      ),
    );
  }

  Widget _screeningTile(String key, String title) {
    return CheckboxListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(title),
      value: values[key] ?? false,
      onChanged: (value) => onChanged(key, value ?? false),
      controlAffinity: ListTileControlAffinity.leading,
    );
  }
}

class AgreementSection extends StatelessWidget {
  const AgreementSection({
    super.key,
    required this.accepted,
    required this.onChanged,
  });

  final bool accepted;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    return ProfileFormSection(
      title: 'Qima AI Nutrition Disclaimer & User Agreement',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            height: 180,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(8),
            ),
            child: const SingleChildScrollView(child: Text(qimaAgreementText)),
          ),
          const SizedBox(height: 8),
          CheckboxListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text(
              'I have read and agree to the Qima AI Nutrition Disclaimer & User Agreement.',
            ),
            value: accepted,
            onChanged: onChanged == null
                ? null
                : (value) => onChanged!(value ?? false),
            controlAffinity: ListTileControlAffinity.leading,
          ),
        ],
      ),
    );
  }
}

class SourceMetadata extends StatelessWidget {
  const SourceMetadata({super.key, required this.raw});

  final Map<String, Object?> raw;

  @override
  Widget build(BuildContext context) {
    final lines = <String>[];
    final source = raw['source'];
    if (source is Map) {
      lines.add('Source: ${compactJson(source)}');
    }
    final confidence = number(raw['confidence']);
    if (confidence != null) {
      lines.add('Confidence: ${(confidence * 100).toStringAsFixed(0)}%');
    }
    final quality = raw['data_quality'];
    if (quality is Map) {
      lines.add('Data quality: ${quality['completeness'] ?? 'Unavailable'}');
    }
    final estimateQuality = raw['estimate_quality'];
    if (estimateQuality is Map) {
      lines.add('Estimate quality: ${compactJson(estimateQuality)}');
    }
    final safety = raw['safety_flags'];
    if (safety is List && safety.isNotEmpty) {
      lines.add('Safety flags: ${safety.join(', ')}');
    }
    if (lines.isEmpty) {
      return const SizedBox.shrink();
    }
    return NoticeCard(
      icon: Icons.source_outlined,
      title: 'Contract metadata',
      message: lines.join('\n'),
    );
  }
}

class DebugPayload extends StatelessWidget {
  const DebugPayload({super.key, required this.raw});

  final Map<String, Object?> raw;

  @override
  Widget build(BuildContext context) {
    final latency = raw['latency_ms'];
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      title: const Text('Debug payload'),
      subtitle: Text(
        latency == null ? 'Raw response' : 'Latency: ${latency}ms',
      ),
      children: [
        SelectableText(
          const JsonEncoder.withIndent('  ').convert(raw),
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ],
    );
  }
}

class NutritionRow {
  const NutritionRow({required this.label, required this.value});

  final String label;
  final String value;
}

class VisionCandidate {
  const VisionCandidate({required this.name, required this.confidence});

  final String name;
  final double? confidence;
}

class InventoryItemRecord {
  const InventoryItemRecord({
    required this.id,
    required this.name,
    required this.normalizedName,
    required this.sourceMethod,
    required this.sourceRef,
    required this.sourceProductId,
  });

  final int id;
  final String name;
  final String normalizedName;
  final String sourceMethod;
  final String? sourceRef;
  final String? sourceProductId;
}

class InventoryImageSelection {
  const InventoryImageSelection({
    required this.imageId,
    required this.recognizedIngredients,
    required this.selectedIngredients,
  });

  final String imageId;
  final List<String> recognizedIngredients;
  final List<String> selectedIngredients;
}

class RecipeSuggestionRecord {
  const RecipeSuggestionRecord({
    required this.recipeId,
    required this.title,
    required this.matchScore,
    required this.matchedIngredients,
    required this.missingIngredients,
  });

  final String recipeId;
  final String title;
  final double? matchScore;
  final List<String> matchedIngredients;
  final List<String> missingIngredients;

  String get summary {
    final parts = <String>[];
    if (matchScore != null) {
      parts.add('Match ${(matchScore! * 100).toStringAsFixed(0)}%');
    }
    if (matchedIngredients.isNotEmpty) {
      parts.add('Using ${matchedIngredients.take(4).join(', ')}');
    }
    if (missingIngredients.isNotEmpty) {
      parts.add('Missing ${missingIngredients.take(4).join(', ')}');
    }
    return parts.isEmpty ? recipeId : parts.join(' | ');
  }
}

class RecipeChatTurn {
  const RecipeChatTurn({required this.role, required this.content});

  final String role;
  final String content;

  Map<String, Object?> toRequestBody() {
    return {'role': role, 'content': content};
  }
}

List<InventoryItemRecord> inventoryItemsFromPayload(Map<String, Object?> raw) {
  final rawItems = raw['items'];
  if (rawItems is! List) {
    return const [];
  }

  final items = <InventoryItemRecord>[];
  for (final item in rawItems) {
    if (item is! Map) {
      continue;
    }

    final id = _asInt(item['id']);
    final name = text(item['name'], fallback: '').trim();
    if (id == null || name.isEmpty) {
      continue;
    }

    items.add(
      InventoryItemRecord(
        id: id,
        name: name,
        normalizedName: text(item['normalized_name'], fallback: '').trim(),
        sourceMethod: text(item['source_method'], fallback: 'manual').trim(),
        sourceRef: text(item['source_ref'], fallback: '').trim().isEmpty
            ? null
            : text(item['source_ref'], fallback: '').trim(),
        sourceProductId:
            text(item['source_product_id'], fallback: '').trim().isEmpty
            ? null
            : text(item['source_product_id'], fallback: '').trim(),
      ),
    );
  }
  return items;
}

Map<String, Object?> buildInventoryManualAddBody(List<String> itemNames) {
  final cleaned = <String>[];
  for (final item in itemNames) {
    final value = item.trim();
    if (value.isEmpty) {
      continue;
    }
    cleaned.add(value);
  }
  return {'items': cleaned};
}

Map<String, Object?> buildInventoryImageAddBody(
  InventoryImageSelection selection,
) {
  return {
    'image_id': selection.imageId.trim(),
    'recognized_ingredients': [
      for (final ingredient in selection.recognizedIngredients)
        if (ingredient.trim().isNotEmpty) ingredient.trim(),
    ],
    'selected_ingredients': [
      for (final ingredient in selection.selectedIngredients)
        if (ingredient.trim().isNotEmpty) ingredient.trim(),
    ],
  };
}

Map<String, Object?> buildRecipeSuggestRequestBody({
  required String budgetLevel,
  required List<int> inventoryItemIds,
  required List<String> pantryItems,
  List<String> recognizedIngredients = const [],
  List<String> dietaryFilters = const [],
  List<String> excludedIngredients = const [],
  int? maxResults,
}) {
  final dedupedPantryItems = <String>[];
  final seenPantry = <String>{};
  for (final item in pantryItems) {
    final cleaned = item.trim();
    if (cleaned.isEmpty) {
      continue;
    }
    final key = cleaned.toLowerCase();
    if (seenPantry.contains(key)) {
      continue;
    }
    seenPantry.add(key);
    dedupedPantryItems.add(cleaned);
  }

  final dedupedInventoryIds = <int>[];
  final seenIds = <int>{};
  for (final id in inventoryItemIds) {
    if (id < 1 || seenIds.contains(id)) {
      continue;
    }
    seenIds.add(id);
    dedupedInventoryIds.add(id);
  }

  final dedupedRecognizedIngredients = <String>[];
  final seenRecognized = <String>{};
  for (final item in recognizedIngredients) {
    final cleaned = item.trim();
    if (cleaned.isEmpty) {
      continue;
    }
    final key = cleaned.toLowerCase();
    if (seenRecognized.contains(key)) {
      continue;
    }
    seenRecognized.add(key);
    dedupedRecognizedIngredients.add(cleaned);
  }

  final normalizedBudget = ['low', 'mid', 'high'].contains(budgetLevel)
      ? budgetLevel
      : 'mid';

  return {
    if (dedupedPantryItems.isNotEmpty) 'pantry_items': dedupedPantryItems,
    if (dedupedRecognizedIngredients.isNotEmpty)
      'recognized_ingredients': dedupedRecognizedIngredients,
    if (dedupedInventoryIds.isNotEmpty)
      'inventory_item_ids': dedupedInventoryIds,
    if (dietaryFilters.isNotEmpty) 'dietary_filters': dietaryFilters,
    if (excludedIngredients.isNotEmpty)
      'excluded_ingredients': excludedIngredients,
    ...switch (maxResults) {
      final value? => {'max_results': value},
      null => const <String, Object?>{},
    },
    'budget_level': normalizedBudget,
  };
}

List<RecipeSuggestionRecord> recipeSuggestionsFromPayload(
  Map<String, Object?>? raw,
) {
  final rawRecipes = raw?['recipes'];
  if (rawRecipes is! List) {
    return const [];
  }

  final recipes = <RecipeSuggestionRecord>[];
  for (final item in rawRecipes) {
    if (item is! Map) {
      continue;
    }
    final recipeId = text(item['recipe_id'], fallback: '').trim();
    final title = text(item['title'], fallback: '').trim();
    if (recipeId.isEmpty || title.isEmpty) {
      continue;
    }
    recipes.add(
      RecipeSuggestionRecord(
        recipeId: recipeId,
        title: title,
        matchScore: number(item['match_score']),
        matchedIngredients: textList(item['matched_ingredients']),
        missingIngredients: textList(item['missing_ingredients']),
      ),
    );
  }
  return recipes;
}

Map<String, Object?> buildRecipeDiscussRequestBody({
  required String recipeId,
  required RecipeSuggestionRecord? selectedRecipe,
  required String question,
  required List<RecipeChatTurn> conversationHistory,
}) {
  final cleanedRecipeId = recipeId.trim();
  final cleanedQuestion = question.trim();
  final body = <String, Object?>{'question': cleanedQuestion};
  if (cleanedRecipeId.isNotEmpty) {
    body['recipe_id'] = cleanedRecipeId;
  }
  if (selectedRecipe != null) {
    body['candidate_context'] = {
      'title': selectedRecipe.title,
      'matched_ingredients': selectedRecipe.matchedIngredients,
      'missing_ingredients': selectedRecipe.missingIngredients,
    };
  }

  final recentTurns = <Map<String, Object?>>[];
  for (final turn in conversationHistory.reversed) {
    if (recentTurns.length >= 8) {
      break;
    }
    final role = turn.role.trim();
    final content = turn.content.trim();
    if ((role == 'user' || role == 'assistant') && content.isNotEmpty) {
      recentTurns.add({'role': role, 'content': content});
    }
  }
  if (recentTurns.isNotEmpty) {
    body['conversation_history'] = recentTurns.reversed.toList();
  }
  return body;
}

String? inventoryBarcodeFromScanPayload(Map<String, Object?> raw) {
  final barcodePattern = RegExp(r'^[0-9]{8,14}$');

  final source = raw['source'];
  if (source is Map) {
    final providerProductId = text(
      source['provider_product_id'],
      fallback: '',
    ).trim();
    if (barcodePattern.hasMatch(providerProductId)) {
      return providerProductId;
    }
  }

  final productId = text(raw['product_id'], fallback: '').trim();
  if (productId.isNotEmpty) {
    final offMatch = RegExp(r'^off:([0-9]{8,14})$').firstMatch(productId);
    if (offMatch != null) {
      return offMatch.group(1);
    }

    if (barcodePattern.hasMatch(productId)) {
      return productId;
    }
  }

  final explicitBarcode = text(raw['barcode'], fallback: '').trim();
  if (barcodePattern.hasMatch(explicitBarcode)) {
    return explicitBarcode;
  }

  return null;
}

const visionNutritionConfidenceCutoff = 0.70;
const _unknownVisionDishNames = {
  'unknown',
  'unknown food',
  'unknown food item',
};

bool isBarcodeScanPayload(Map<String, Object?> raw) {
  return raw['product_id'] != null && raw['nutrition'] is Map;
}

bool isVisionIdentifyPayload(Map<String, Object?> raw) {
  final source = raw['source'];
  return raw['image_id'] != null &&
      raw['dish_candidates'] is List &&
      raw['ingredients'] is List &&
      source is Map &&
      source['source_type'] == 'vision_model';
}

bool isNutritionEstimatePayload(Map<String, Object?> raw) {
  return raw['matched_dish'] is Map &&
      raw['nutrients'] is Map &&
      raw['source'] is Map &&
      number(raw['confidence']) != null;
}

Map<String, Object?>? nutritionRequestBodyFromVisionPayload(
  Map<String, Object?> raw,
) {
  final ingredients = _distinctVisionCandidateNames(
    visionCandidates(raw['ingredients']),
  );
  final dishCandidates = visionCandidates(raw['dish_candidates']);
  if (dishCandidates.isNotEmpty) {
    final topCandidate = dishCandidates.first;
    final confidence = topCandidate.confidence;
    final dishName = topCandidate.name.trim();
    if (confidence != null &&
        confidence >= visionNutritionConfidenceCutoff &&
        dishName.isNotEmpty &&
        !_isUnknownVisionDishName(dishName)) {
      return <String, Object?>{
        'input_type': 'recognized_dish',
        'recognized_dish': dishName,
        if (ingredients.isNotEmpty) 'ingredients': ingredients,
      };
    }
  }

  if (ingredients.isEmpty) {
    return null;
  }
  return <String, Object?>{
    'input_type': 'ingredient_set',
    'ingredients': ingredients,
  };
}

bool _isUnknownVisionDishName(String value) {
  return _unknownVisionDishNames.contains(_normalizedVisionName(value));
}

String _normalizedVisionName(String value) {
  return value.replaceAll(RegExp(r'\s+'), ' ').trim().toLowerCase();
}

List<String> _distinctVisionCandidateNames(List<VisionCandidate> candidates) {
  final seen = <String>{};
  final names = <String>[];
  for (final candidate in candidates) {
    final name = candidate.name.trim();
    if (name.isEmpty) {
      continue;
    }
    final key = _normalizedVisionName(name);
    if (key.isEmpty || seen.contains(key)) {
      continue;
    }
    seen.add(key);
    names.add(name);
  }
  return names;
}

List<VisionCandidate> visionCandidates(Object? rawCandidates) {
  if (rawCandidates is! List) {
    return const [];
  }

  final candidates = <VisionCandidate>[];
  for (final item in rawCandidates) {
    if (item is Map) {
      final name = text(
        item['name'] ?? item['text'] ?? item['ingredient'],
        fallback: '',
      ).trim();
      if (name.isEmpty) {
        continue;
      }
      candidates.add(
        VisionCandidate(name: name, confidence: number(item['confidence'])),
      );
      continue;
    }

    final name = text(item, fallback: '').trim();
    if (name.isNotEmpty) {
      candidates.add(VisionCandidate(name: name, confidence: null));
    }
  }
  return candidates;
}

List<NutritionRow> nutritionEstimateRows(Object? rawNutrients) {
  if (rawNutrients is! Map) {
    return const [];
  }

  final rows = <NutritionRow>[];
  void addValue(
    List<String> keys,
    String label, {
    required String unit,
    required int decimals,
  }) {
    double? value;
    for (final key in keys) {
      value = number(rawNutrients[key]);
      if (value != null) {
        break;
      }
    }
    if (value == null) {
      return;
    }
    rows.add(
      NutritionRow(
        label: label,
        value: '${formatNutritionNumber(value, decimals: decimals)} $unit',
      ),
    );
  }

  addValue(
    ['calories_kcal', 'energy_kcal'],
    'Calories',
    unit: 'kcal',
    decimals: 0,
  );
  addValue(['protein_g'], 'Protein', unit: 'g', decimals: 1);
  addValue(['carbohydrates_g', 'carbs_g'], 'Carbs', unit: 'g', decimals: 1);
  addValue(['fat_g'], 'Fat', unit: 'g', decimals: 1);
  addValue(['fiber_g'], 'Fiber', unit: 'g', decimals: 1);
  addValue(['sugar_g', 'sugars_g'], 'Sugar', unit: 'g', decimals: 1);
  addValue(['sodium_mg'], 'Sodium', unit: 'mg', decimals: 0);
  return rows;
}

String visionCandidateChipLabel(VisionCandidate candidate) {
  final confidence = candidate.confidence;
  if (confidence == null) {
    return candidate.name;
  }
  return '${candidate.name} ${formatConfidence(confidence)}';
}

String formatConfidence(double confidence) {
  return '${(confidence * 100).toStringAsFixed(0)}%';
}

List<String> textList(Object? rawValues) {
  if (rawValues is! List) {
    return const [];
  }

  final values = <String>[];
  for (final item in rawValues) {
    final value = text(item, fallback: '').trim();
    if (value.isNotEmpty) {
      values.add(value);
    }
  }
  return values;
}

String nutritionBasisDisplayLabel(Object? rawNutrition) {
  if (rawNutrition is Map) {
    final explicit = text(rawNutrition['basis_label'], fallback: '').trim();
    if (explicit.isNotEmpty) {
      return explicit[0].toLowerCase() + explicit.substring(1);
    }
    final basis = text(
      rawNutrition['basis'],
      fallback: '',
    ).trim().toLowerCase();
    switch (basis) {
      case 'per_100ml':
        return 'per 100 ml';
      case 'per_serving':
        return 'per serving';
      default:
        return 'per 100 g';
    }
  }
  return 'per 100 g';
}

List<NutritionRow> nutritionRows(Object? rawNutrition) {
  if (rawNutrition is! Map) {
    return const [];
  }

  final facts = rawNutrition['facts'];
  if (facts is List && facts.isNotEmpty) {
    final rows = <NutritionRow>[];
    void addFact(List<String> keys, String label) {
      final fact = facts.cast<Object?>().whereType<Map>().firstWhere(
        (item) => keys.contains(text(item['key'], fallback: '').trim()),
        orElse: () => const {},
      );
      if (fact.isEmpty) {
        return;
      }
      final display = text(fact['display_value'], fallback: '').trim();
      if (display.isEmpty) {
        return;
      }
      rows.add(NutritionRow(label: label, value: display));
    }

    addFact(['energy_kcal', 'calories_kcal'], 'Energy');
    addFact(['protein_g'], 'Protein');
    addFact(['carbohydrates_g', 'carbs_g'], 'Carbs');
    addFact(['fat_g'], 'Fat');
    addFact(['sugars_g'], 'Sugars');
    addFact(['sodium_mg'], 'Sodium');
    addFact(['salt_g'], 'Salt');
    if (rows.isNotEmpty) {
      return rows;
    }
  }

  final values = rawNutrition['values'];
  if (values is! Map) {
    return const [];
  }

  final rows = <NutritionRow>[];
  void addValue(
    List<String> keys,
    String label, {
    required String unit,
    required int decimals,
  }) {
    double? value;
    for (final key in keys) {
      value = number(values[key]);
      if (value != null) {
        break;
      }
    }
    if (value == null) {
      return;
    }
    rows.add(
      NutritionRow(
        label: label,
        value: '${formatNutritionNumber(value, decimals: decimals)} $unit',
      ),
    );
  }

  addValue(
    ['energy_kcal', 'calories_kcal'],
    'Energy',
    unit: 'kcal',
    decimals: 0,
  );
  addValue(['protein_g'], 'Protein', unit: 'g', decimals: 1);
  addValue(['carbohydrates_g', 'carbs_g'], 'Carbs', unit: 'g', decimals: 1);
  addValue(['fat_g'], 'Fat', unit: 'g', decimals: 1);
  addValue(['sugars_g'], 'Sugars', unit: 'g', decimals: 1);
  addValue(['sodium_mg'], 'Sodium', unit: 'mg', decimals: 0);
  addValue(['salt_g'], 'Salt', unit: 'g', decimals: 2);
  return rows;
}

String ingredientsParagraph(Object? rawIngredients) {
  if (rawIngredients is! List || rawIngredients.isEmpty) {
    return 'Unavailable';
  }

  final ingredients = <String>[];
  for (final item in rawIngredients) {
    String ingredient = '';
    if (item is Map) {
      ingredient = text(
        item['text'] ?? item['name'] ?? item['ingredient'],
        fallback: '',
      ).trim();
    } else {
      ingredient = text(item, fallback: '').trim();
    }
    if (ingredient.isEmpty) {
      continue;
    }
    ingredients.add(normalizeIngredient(ingredient));
  }

  if (ingredients.isEmpty) {
    return 'Unavailable';
  }

  final sentence = ingredients.join(', ');
  final first = sentence[0].toUpperCase();
  final rest = sentence.substring(1);
  return '$first$rest.';
}

String normalizeIngredient(String value) {
  final compact = value.replaceAll(RegExp(r'\s+'), ' ').trim();
  if (compact.isEmpty) {
    return compact;
  }

  if (compact == compact.toUpperCase() || compact == compact.toLowerCase()) {
    return compact.toLowerCase();
  }
  return compact;
}

Map<String, List<String>> allergensBySeverity(Object? rawAllergens) {
  final grouped = <String, List<String>>{
    'contains': <String>[],
    'may_contain': <String>[],
  };
  if (rawAllergens is! List) {
    return grouped;
  }

  for (final item in rawAllergens) {
    String name = '';
    String severity = 'contains';

    if (item is Map) {
      name = text(item['name'] ?? item['allergen'], fallback: '').trim();
      final rawSeverity = text(
        item['severity'],
        fallback: 'contains',
      ).trim().toLowerCase();
      severity = rawSeverity == 'may_contain' ? 'may_contain' : 'contains';
    } else {
      name = text(item, fallback: '').trim();
    }

    if (name.isEmpty) {
      continue;
    }
    grouped[severity]?.add(titleCase(name));
  }

  return grouped;
}

String titleCase(String value) {
  final words = value.replaceAll(RegExp(r'\s+'), ' ').trim().split(' ');
  return words
      .where((word) => word.isNotEmpty)
      .map((word) {
        if (word.length == 1) {
          return word.toUpperCase();
        }
        return '${word[0].toUpperCase()}${word.substring(1).toLowerCase()}';
      })
      .join(' ');
}

Map<String, String> summarizePayload(Map<String, Object?> raw) {
  final entries = <String, String>{};
  void add(String label, Object? value) {
    final display = displayValue(value);
    if (display.isNotEmpty) {
      entries[label] = display;
    }
  }

  final rawNutrition =
      raw['nutrition'] ?? raw['nutrients'] ?? raw['nutrition_targets'];
  final friendlyNutrition = formatNutritionSummary(rawNutrition);
  final friendlyIngredients = formatIngredientsSummary(raw['ingredients']);
  final friendlyAllergens = formatAllergensSummary(raw['allergens']);
  final friendlyPlan = formatPlanSummary(raw);

  add('Status', raw['status']);
  add('Product', raw['name']);
  add('Brand', raw['brand']);
  add('Image id', raw['image_id']);
  add('Matched dish', raw['matched_dish']);
  add('Nutrition', friendlyNutrition ?? rawNutrition);
  add('Ingredients', friendlyIngredients ?? raw['ingredients']);
  add('Allergens', friendlyAllergens ?? raw['allergens']);
  add('Dish candidates', raw['dish_candidates']);
  add('Recipes', raw['recipes']);
  add('Answer', raw['answer']);
  add('References', raw['source_references'] ?? raw['grounded_references']);
  add('Profile id', raw['profile_id']);
  add('Support status', raw['support_status']);
  add('Plan id', raw['plan_id']);
  if (friendlyPlan != null) {
    add('Plan', friendlyPlan);
  } else {
    add('Meals', raw['meals']);
  }
  add('Rationale', raw['rationale']);
  add('Price items', raw['item_costs']);
  add('Marker result', raw['marker']);
  add('Food guidance', raw['food_guidance']);
  add('Warnings', raw['warnings']);
  if (entries.isEmpty) {
    add('Response', raw);
  }
  return entries;
}

String? formatNutritionSummary(Object? rawNutrition) {
  if (rawNutrition is! Map) {
    return null;
  }

  final lines = <String>[];
  final basisLabel = text(rawNutrition['basis_label'], fallback: '').trim();
  final servingLabel = text(rawNutrition['serving_label'], fallback: '').trim();
  if (basisLabel.isNotEmpty) {
    lines.add(basisLabel);
  }
  if (servingLabel.isNotEmpty) {
    lines.add(servingLabel);
  }

  final facts = rawNutrition['facts'];
  if (facts is List && facts.isNotEmpty) {
    for (final item in facts) {
      if (item is! Map) {
        continue;
      }
      final label = text(item['label'], fallback: '').trim();
      final display = text(item['display_value'], fallback: '').trim();
      if (label.isEmpty || display.isEmpty) {
        continue;
      }
      lines.add('$label: $display');
    }
    return lines.isEmpty ? null : lines.join('\n');
  }

  final values = rawNutrition['values'];
  if (values is! Map) {
    return lines.isEmpty ? null : lines.join('\n');
  }

  void addNutrient(
    String key,
    String label, {
    String unit = 'g',
    int decimals = 1,
  }) {
    final value = number(values[key]);
    if (value == null) {
      return;
    }
    lines.add(
      '$label: ${formatNutritionNumber(value, decimals: decimals)} $unit',
    );
  }

  addNutrient('energy_kcal', 'Energy', unit: 'kcal', decimals: 0);
  addNutrient('calories_kcal', 'Calories', unit: 'kcal', decimals: 0);
  addNutrient('protein_g', 'Protein');
  addNutrient('carbohydrates_g', 'Carbohydrates');
  addNutrient('carbs_g', 'Carbohydrates');
  addNutrient('fat_g', 'Fat');
  addNutrient('sugars_g', 'Sugars');
  addNutrient('fiber_g', 'Fiber');
  addNutrient('sodium_mg', 'Sodium', unit: 'mg', decimals: 0);
  addNutrient('salt_g', 'Salt', decimals: 2);

  return lines.isEmpty ? null : lines.join('\n');
}

String? formatPlanSummary(Map<String, Object?> raw) {
  final generatedPlan = raw['generated_plan'];
  if (generatedPlan is Map) {
    final formattedMessage = text(
      generatedPlan['formatted_message'],
      fallback: '',
    ).trim();
    if (formattedMessage.isNotEmpty) {
      return formattedMessage;
    }
  }

  final meals = raw['meals'];
  if (meals is! List || meals.isEmpty) {
    return null;
  }

  final lines = <String>[];
  final target = raw['nutrition_targets'];
  if (target is Map) {
    final calories = target['calories_kcal'];
    final basis = text(target['target_basis'], fallback: '').trim();
    if (calories != null) {
      final label = basis.isEmpty ? '' : ' ($basis)';
      lines.add('Daily target: ${displayValue(calories)} kcal$label');
    }
  }

  for (var index = 0; index < meals.length; index += 1) {
    final meal = meals[index];
    if (meal is! Map) {
      continue;
    }

    final title = text(meal['title'], fallback: 'Meal ${index + 1}').trim();
    final type = titleCase(text(meal['meal_type'], fallback: 'meal'));
    lines.add('${index + 1}. $type: $title');

    final details = <String>[];
    final nutrition = meal['estimated_nutrition'];
    if (nutrition is Map && nutrition['calories_kcal'] != null) {
      details.add('${displayValue(nutrition['calories_kcal'])} kcal');
    }

    final cost = meal['estimated_cost'];
    if (cost is Map) {
      final totalCost = cost['total_cost'];
      final currency = text(cost['currency'], fallback: 'EGP');
      final quality = text(cost['estimate_quality'], fallback: '').trim();
      if (totalCost != null) {
        final qualityLabel = quality.isEmpty ? '' : ' | $quality';
        details.add('$currency ${displayValue(totalCost)}$qualityLabel');
      }
    }

    if (details.isNotEmpty) {
      lines.add('   ${details.join(' | ')}');
    }

    final matched = _compactStringList(meal['matched_ingredients']);
    if (matched.isNotEmpty) {
      lines.add('   Uses: ${matched.join(', ')}');
    }

    final missing = _compactStringList(meal['missing_ingredients']);
    if (missing.isNotEmpty) {
      lines.add('   Need: ${missing.join(', ')}');
    }

    final warnings = _compactStringList(meal['warnings']);
    if (warnings.isNotEmpty) {
      lines.add('   Notes: ${warnings.join(' ')}');
    }
  }

  return lines.isEmpty ? null : lines.join('\n');
}

List<String> _compactStringList(Object? value) {
  if (value is! List) {
    return const [];
  }

  return value
      .map((item) => text(item, fallback: '').trim())
      .where((item) => item.isNotEmpty)
      .toList();
}

String formatNutritionNumber(double value, {required int decimals}) {
  final rounded = value.toStringAsFixed(decimals);
  if (!rounded.contains('.')) {
    return rounded;
  }
  return rounded.replaceFirst(RegExp(r'\.?0+$'), '');
}

String? formatIngredientsSummary(Object? rawIngredients) {
  if (rawIngredients is! List) {
    return null;
  }
  if (rawIngredients.isEmpty) {
    return 'None listed';
  }

  final lines = <String>[];
  for (final item in rawIngredients) {
    if (item is Map) {
      final ingredientText = text(
        item['text'] ?? item['name'] ?? item['ingredient'],
        fallback: '',
      ).trim();
      if (ingredientText.isEmpty) {
        continue;
      }
      final isAllergen = item['is_allergen'] == true;
      lines.add(isAllergen ? '$ingredientText (allergen)' : ingredientText);
      continue;
    }

    final value = text(item, fallback: '').trim();
    if (value.isNotEmpty) {
      lines.add(value);
    }
  }

  return lines.isEmpty ? null : lines.join('\n');
}

String? formatAllergensSummary(Object? rawAllergens) {
  if (rawAllergens is! List) {
    return null;
  }
  if (rawAllergens.isEmpty) {
    return 'None declared';
  }

  final lines = <String>[];
  for (final item in rawAllergens) {
    if (item is Map) {
      final name = text(item['name'] ?? item['allergen'], fallback: '').trim();
      if (name.isEmpty) {
        continue;
      }
      final severity = _allergenSeverityLabel(item['severity']);
      lines.add('$name ($severity)');
      continue;
    }

    final value = text(item, fallback: '').trim();
    if (value.isNotEmpty) {
      lines.add(value);
    }
  }

  return lines.isEmpty ? null : lines.join('\n');
}

String _allergenSeverityLabel(Object? severity) {
  final normalized = text(severity, fallback: 'unknown').trim().toLowerCase();
  switch (normalized) {
    case 'contains':
      return 'contains';
    case 'may_contain':
      return 'may contain';
    default:
      return 'unknown';
  }
}

String displayValue(Object? value) {
  if (value == null) {
    return '';
  }
  if (value is String) {
    return value.isEmpty ? 'Unavailable' : value;
  }
  if (value is num || value is bool) {
    return value.toString();
  }
  if (value is List) {
    if (value.isEmpty) {
      return 'None';
    }
    return value.map(displayValue).join('\n');
  }
  if (value is Map) {
    if (value.isEmpty) {
      return 'Unavailable';
    }
    return compactJson(value);
  }
  return value.toString();
}

String compactJson(Object value) {
  try {
    return jsonEncode(value);
  } on Object {
    return value.toString();
  }
}

String text(Object? value, {required String fallback}) {
  if (value is String) {
    return value;
  }
  if (value == null) {
    return fallback;
  }
  return value.toString();
}

double? number(Object? value) {
  if (value is num) {
    return value.toDouble();
  }
  if (value is String) {
    return double.tryParse(value);
  }
  return null;
}

int? _asInt(Object? value) {
  if (value is int) {
    return value;
  }
  if (value is num) {
    return value.toInt();
  }
  if (value is String) {
    return int.tryParse(value);
  }
  return null;
}

Map<String, bool> defaultSafetyScreening() {
  return {
    'pregnant': false,
    'breastfeeding': false,
    'eating_disorder_history': false,
    'under_18': false,
    'medical_condition_affects_diet': false,
    'abnormal_labs_or_health_concerns': false,
    'none_of_above': false,
  };
}

const _safetyRestrictionKeys = [
  'pregnant',
  'breastfeeding',
  'eating_disorder_history',
  'under_18',
  'medical_condition_affects_diet',
  'abnormal_labs_or_health_concerns',
];

bool safetyScreeningHasRestriction(Map<String, bool> values) {
  return _safetyRestrictionKeys.any((key) => values[key] == true);
}

bool safetyScreeningCompleted(Map<String, bool> values) {
  return values['none_of_above'] == true ||
      safetyScreeningHasRestriction(values);
}

void updateSafetyScreening(Map<String, bool> values, String key, bool value) {
  values[key] = value;
  if (key == 'none_of_above' && value) {
    for (final restrictionKey in _safetyRestrictionKeys) {
      values[restrictionKey] = false;
    }
    return;
  }
  if (key != 'none_of_above' && value) {
    values['none_of_above'] = false;
  }
}

Map<String, Object?> safetyScreeningBody(Map<String, bool> values) {
  return {for (final entry in values.entries) entry.key: entry.value};
}

void applySafetyScreeningFromProfile(Map<String, bool> values, Object? raw) {
  values
    ..clear()
    ..addAll(defaultSafetyScreening());
  if (raw is! Map) {
    return;
  }
  for (final key in values.keys.toList()) {
    values[key] = raw[key] == true;
  }
}

String inputNumberText(Object? value) {
  final parsed = number(value);
  if (parsed == null) {
    return '';
  }
  final raw = parsed.toString();
  return raw.endsWith('.0') ? parsed.toInt().toString() : raw;
}

String commaSeparatedText(Object? value) {
  if (value is! List) {
    return '';
  }
  return value
      .map((item) => text(item, fallback: '').trim())
      .where((item) {
        return item.isNotEmpty;
      })
      .join(', ');
}

String optionFromProfile(
  Object? value,
  List<String> options, {
  required String fallback,
}) {
  final normalized = text(value, fallback: '').trim();
  return options.contains(normalized) ? normalized : fallback;
}

Map<String, Object?> priceBudgetContext({
  double? maxTotalCost,
  String currency = 'EGP',
  String? geography,
}) {
  final context = <String, Object?>{'currency': currency};
  if (maxTotalCost != null) {
    context['max_total_cost'] = maxTotalCost;
  }
  if (geography != null && geography.isNotEmpty) {
    context['geography'] = geography;
  }
  return context;
}

List<DropdownMenuItem<String>> options(List<String> values) {
  return [
    for (final value in values)
      DropdownMenuItem(value: value, child: Text(value.replaceAll('_', ' '))),
  ];
}

String? validateEmailAddress(String rawEmail) {
  final email = rawEmail.trim().toLowerCase();
  if (email.isEmpty) {
    return 'Email is required.';
  }
  if (!_emailRegex.hasMatch(email)) {
    return 'Please enter a valid email address.';
  }
  return null;
}

void showValidation(BuildContext context, String message) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
}

extension FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull {
    final iterator = this.iterator;
    if (iterator.moveNext()) {
      return iterator.current;
    }
    return null;
  }
}

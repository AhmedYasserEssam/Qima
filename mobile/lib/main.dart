import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:device_preview/device_preview.dart';
import 'package:flutter/foundation.dart';

void main() {
  runApp(
    DevicePreview(
      enabled: !kReleaseMode,
      builder: (context) => const ProviderScope(child: QimaApp()),
    ),
  );
}

const apiBaseUrl = String.fromEnvironment(
  'QIMA_API_BASE_URL',
  defaultValue: 'http://127.0.0.1:8000',
);

final apiClientProvider = Provider<ApiClient>((ref) {
  return ApiClient(baseUrl: apiBaseUrl, client: http.Client());
});

final debugModeProvider = StateProvider<bool>((ref) => false);
final profileIdProvider = StateProvider<String?>((ref) => null);

final healthProvider = FutureProvider<ApiPayload>((ref) async {
  return ref
      .read(apiClientProvider)
      .get('/v1/health', requiredFields: ['status']);
});

final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/scan',
    routes: [
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
    unawaited(_loadProfileId());
  }

  Future<void> _loadProfileId() async {
    final prefs = await SharedPreferences.getInstance();
    ref.read(profileIdProvider.notifier).state = prefs.getString('profile_id');
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
  ApiClient({required this.baseUrl, required this.client});

  final String baseUrl;
  final http.Client client;

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Future<ApiPayload> get(
    String path, {
    required List<String> requiredFields,
  }) async {
    try {
      final response = await client.get(_uri(path));
      return _parseResponse(response, requiredFields);
    } on Exception catch (error) {
      throw ApiFailure.network(error.toString());
    }
  }

  Future<ApiPayload> post(
    String path,
    Map<String, Object?> body, {
    required List<String> requiredFields,
  }) async {
    try {
      final response = await client.post(
        _uri(path),
        headers: {'content-type': 'application/json'},
        body: jsonEncode(body),
      );
      return _parseResponse(response, requiredFields);
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
      final request = http.MultipartRequest('POST', _uri(path))
        ..fields['locale'] = 'en'
        ..files.add(await http.MultipartFile.fromPath('image', image.path));
      final streamed = await client.send(request);
      final response = await http.Response.fromStream(streamed);
      return _parseResponse(response, requiredFields);
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
    this.details,
  });

  factory ApiFailure.network(String details) {
    return ApiFailure(
      message: 'Could not reach the FastAPI backend.',
      retryable: true,
      details: details,
    );
  }

  factory ApiFailure.fromResponse(int statusCode, Map<String, Object?> raw) {
    final error = raw['error'];
    if (error is Map) {
      return ApiFailure(
        message: text(error['message'], fallback: 'Request failed.'),
        retryable: error['retryable'] == true,
        statusCode: statusCode,
        details: jsonEncode(raw),
      );
    }
    return ApiFailure(
      message: 'Request failed with HTTP $statusCode.',
      retryable: statusCode >= 500 || statusCode == 429,
      statusCode: statusCode,
      details: jsonEncode(raw),
    );
  }

  final String message;
  final bool retryable;
  final int? statusCode;
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
  if (missing is List && missing.isNotEmpty) {
    reasons.add('Some ingredients are missing.');
  }
  final recipes = raw['recipes'];
  if (recipes is List) {
    for (final recipe in recipes) {
      if (recipe is Map &&
          recipe['missing_ingredients'] is List &&
          (recipe['missing_ingredients'] as List).isNotEmpty) {
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

  Future<void> run(Future<ApiPayload> Function(ApiClient client) action) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => action(_client));
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
    ref.listen<AsyncValue<ApiPayload>?>(scanControllerProvider, (previous, next) {
      final didBecomeSuccessful =
          (next is AsyncData<ApiPayload>) && (previous is! AsyncData<ApiPayload>);
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
          ),
        ),
        AsyncPayloadView(
          title: 'Nutrition estimate',
          value: nutritionState,
          onRetry: _estimateNutrition,
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
    ref
        .read(nutritionControllerProvider.notifier)
        .run(
          (client) => client.post(
            '/v1/nutrition/estimate',
            {'input_type': 'recognized_dish', 'recognized_dish': dish},
            requiredFields: [
              'matched_dish',
              'nutrients',
              'confidence',
              'source',
            ],
          ),
        );
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
  final pantryController = TextEditingController(text: 'rice, lentils');
  final budgetController = TextEditingController(text: '60');
  final geographyController = TextEditingController(text: 'Cairo');
  final recipeIdController = TextEditingController(text: 'recipe_stub_001');
  final questionController = TextEditingController(
    text: 'Can you make this recipe more price friendly?',
  );
  bool priceAware = true;
  bool usePantryAsOwned = true;
  String rankingMode = 'budget_friendly';

  @override
  void dispose() {
    pantryController.dispose();
    budgetController.dispose();
    geographyController.dispose();
    recipeIdController.dispose();
    questionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return EndpointPage(
      title: 'Recipes',
      children: [
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
              TextFormField(
                controller: budgetController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Max recipe cost EGP',
                ),
              ),
              TextFormField(
                controller: geographyController,
                decoration: const InputDecoration(labelText: 'Price geography'),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Use price-aware ranking'),
                subtitle: const Text('Estimated, not live market prices.'),
                value: priceAware,
                onChanged: (value) => setState(() => priceAware = value),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Treat pantry as already owned'),
                subtitle: const Text('Ranks by missing ingredient cost.'),
                value: usePantryAsOwned,
                onChanged: priceAware
                    ? (value) => setState(() => usePantryAsOwned = value)
                    : null,
              ),
              DropdownButtonFormField<String>(
                initialValue: rankingMode,
                decoration: const InputDecoration(labelText: 'Ranking mode'),
                items: options([
                  'budget_friendly',
                  'lowest_cost',
                  'best_match',
                  'balanced',
                  'cost_per_protein',
                ]),
                onChanged: priceAware
                    ? (value) =>
                          setState(() => rankingMode = value ?? rankingMode)
                    : null,
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: _suggest,
                icon: const Icon(Icons.restaurant_menu_outlined),
                label: const Text('Suggest recipes'),
              ),
            ],
          ),
        ),
        AsyncPayloadView(
          title: 'Recipe suggestions',
          value: ref.watch(recipeControllerProvider),
          onRetry: _suggest,
        ),
        InputCard(
          title: 'Recipe discussion',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              TextFormField(
                controller: recipeIdController,
                decoration: const InputDecoration(labelText: 'Recipe id'),
              ),
              TextFormField(
                controller: questionController,
                decoration: const InputDecoration(labelText: 'Question'),
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: _discuss,
                icon: const Icon(Icons.forum_outlined),
                label: const Text('Discuss recipe'),
              ),
            ],
          ),
        ),
        AsyncPayloadView(
          title: 'Recipe discussion',
          value: ref.watch(recipeDiscussControllerProvider),
          onRetry: _discuss,
        ),
      ],
    );
  }

  List<String> _items() => pantryController.text
      .split(',')
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toList();

  void _suggest() {
    final items = _items();
    final budget = double.tryParse(budgetController.text.trim());
    final geography = geographyController.text.trim();
    if (items.isEmpty) {
      showValidation(context, 'At least one pantry item is required.');
      return;
    }
    if (priceAware &&
        budgetController.text.trim().isNotEmpty &&
        budget == null) {
      showValidation(context, 'Max recipe cost must be a number.');
      return;
    }
    ref
        .read(recipeControllerProvider.notifier)
        .run(
          (client) => client.post(
            '/v1/recipes/suggest',
            {
              'pantry_items': items,
              'dietary_filters': priceAware ? ['budget_friendly'] : <String>[],
              if (priceAware)
                'budget': priceBudgetContext(
                  maxTotalCost: budget,
                  geography: geography,
                ),
              if (priceAware)
                'price_preferences': {
                  'price_aware': true,
                  'ranking_mode': rankingMode,
                  'include_item_costs': true,
                  'use_pantry_as_owned': usePantryAsOwned,
                },
            },
            requiredFields: ['recipes', 'source'],
          ),
        );
  }

  void _discuss() {
    final question = questionController.text.trim();
    if (question.isEmpty) {
      showValidation(context, 'Question is required.');
      return;
    }
    ref
        .read(recipeDiscussControllerProvider.notifier)
        .run(
          (client) => client.post(
            '/v1/recipes/discuss',
            {
              'recipe_id': recipeIdController.text.trim().isEmpty
                  ? 'recipe_stub_001'
                  : recipeIdController.text.trim(),
              'question': question,
              'conversation_intent': _priceIntent(question)
                  ? 'reduce_cost'
                  : 'explain_recipe',
              'price_context': _priceContext(),
            },
            requiredFields: ['answer', 'grounded_references', 'safety_flags'],
          ),
        );
  }

  Map<String, Object?> _priceContext() {
    final budget = double.tryParse(budgetController.text.trim());
    final geography = geographyController.text.trim();
    return {
      'budget': priceBudgetContext(maxTotalCost: budget, geography: geography),
      'price_preferences': {
        'price_aware': priceAware,
        'ranking_mode': rankingMode,
        'include_item_costs': true,
        'use_pantry_as_owned': usePantryAsOwned,
      },
      'latest_recipe_suggestions':
          ref.read(recipeControllerProvider)?.valueOrNull?.raw['recipes'] ??
          <Object?>[],
    };
  }
}

class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  final ageController = TextEditingController(text: '30');
  final heightController = TextEditingController(text: '170');
  final weightController = TextEditingController(text: '70');
  String sex = 'prefer_not_to_say';
  String activity = 'moderately_active';
  String goal = 'improve_general_health';

  @override
  void dispose() {
    ageController.dispose();
    heightController.dispose();
    weightController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final profileId = ref.watch(profileIdProvider);
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
              if (profileId != null) Text('Cached profile_id: $profileId'),
              TextFormField(
                controller: ageController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Age years'),
              ),
              TextFormField(
                controller: heightController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Height cm'),
              ),
              TextFormField(
                controller: weightController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Weight kg'),
              ),
              DropdownButtonFormField<String>(
                initialValue: sex,
                decoration: const InputDecoration(labelText: 'Sex'),
                items: options([
                  'male',
                  'female',
                  'other',
                  'prefer_not_to_say',
                ]),
                onChanged: (value) => setState(() => sex = value ?? sex),
              ),
              DropdownButtonFormField<String>(
                initialValue: activity,
                decoration: const InputDecoration(labelText: 'Activity level'),
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
                decoration: const InputDecoration(labelText: 'Goal'),
                items: options([
                  'lose_weight',
                  'gain_muscle',
                  'maintain_weight',
                  'improve_general_health',
                ]),
                onChanged: (value) => setState(() => goal = value ?? goal),
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: _saveProfile,
                icon: const Icon(Icons.save_outlined),
                label: const Text('Save profile'),
              ),
            ],
          ),
        ),
        AsyncPayloadView(
          title: 'Profile response',
          value: ref.watch(profileControllerProvider),
          onRetry: _saveProfile,
        ),
      ],
    );
  }

  Map<String, Object?>? _profileBody({String? profileId}) {
    final age = int.tryParse(ageController.text.trim());
    final height = double.tryParse(heightController.text.trim());
    final weight = double.tryParse(weightController.text.trim());
    if (age == null || age < 18 || height == null || weight == null) {
      showValidation(
        context,
        'Age must be 18+, and height/weight must be valid.',
      );
      return null;
    }
    final body = <String, Object?>{
      'age_years': age,
      'sex': sex,
      'height_cm': height,
      'weight_kg': weight,
      'activity_level': activity,
      'goal': goal,
      'allergens': <String>[],
      'dietary_exclusions': <String>[],
      'dietary_preferences': ['egyptian_foods'],
      'exclusion_flags': <String>[],
    };
    if (profileId != null) {
      body['profile_id'] = profileId;
    }
    return body;
  }

  Future<void> _saveProfile() async {
    final currentId = ref.read(profileIdProvider);
    final body = _profileBody(profileId: currentId);
    if (body == null) {
      return;
    }
    await ref
        .read(profileControllerProvider.notifier)
        .run(
          (client) => client.post(
            '/v1/profile/update',
            body,
            requiredFields: [
              'profile_id',
              'normalized_profile',
              'support_status',
            ],
          ),
        );
    final state = ref.read(profileControllerProvider);
    final raw = state?.valueOrNull?.raw;
    final profileId = raw == null
        ? null
        : text(raw['profile_id'], fallback: '');
    if (profileId != null && profileId.isNotEmpty) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('profile_id', profileId);
      ref.read(profileIdProvider.notifier).state = profileId;
    }
  }
}

class PlanScreen extends ConsumerStatefulWidget {
  const PlanScreen({super.key});

  @override
  ConsumerState<PlanScreen> createState() => _PlanScreenState();
}

class _PlanScreenState extends ConsumerState<PlanScreen> {
  final pantryController = TextEditingController(text: 'rice, lentils');
  final budgetController = TextEditingController(text: '120');
  bool useInlineProfile = false;

  @override
  void dispose() {
    pantryController.dispose();
    budgetController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final profileId = ref.watch(profileIdProvider);
    return EndpointPage(
      title: 'Plan',
      children: [
        NoticeCard(
          icon: Icons.health_and_safety_outlined,
          title: 'Safety boundary',
          message: 'Meal guidance is for generally healthy adults.',
        ),
        InputCard(
          title: 'Generate meal plan',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Use inline mock profile'),
                subtitle: Text(
                  profileId == null
                      ? 'No cached profile_id. Inline profile is required.'
                      : 'Cached profile_id: $profileId',
                ),
                value: useInlineProfile || profileId == null,
                onChanged: (value) => setState(() => useInlineProfile = value),
              ),
              TextFormField(
                controller: pantryController,
                decoration: const InputDecoration(labelText: 'Pantry items'),
              ),
              TextFormField(
                controller: budgetController,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Max total cost EGP',
                ),
              ),
              const SizedBox(height: 8),
              FilledButton.icon(
                onPressed: _generate,
                icon: const Icon(Icons.event_note_outlined),
                label: const Text('Generate plan'),
              ),
            ],
          ),
        ),
        AsyncPayloadView(
          title: 'Plan response',
          value: ref.watch(planControllerProvider),
          onRetry: _generate,
        ),
      ],
    );
  }

  void _generate() {
    final profileId = ref.read(profileIdProvider);
    final budget = double.tryParse(budgetController.text.trim());
    final pantry = pantryController.text
        .split(',')
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .map((name) => {'name': name})
        .toList();
    if (profileId == null && !useInlineProfile) {
      showValidation(context, 'Save a profile or enable inline mock profile.');
      return;
    }
    final body = <String, Object?>{
      if (profileId != null && !useInlineProfile) 'profile_id': profileId,
      if (profileId == null || useInlineProfile)
        'profile': {
          'age_years': 30,
          'sex': 'prefer_not_to_say',
          'height_cm': 170,
          'weight_kg': 70,
          'activity_level': 'moderately_active',
          'goal': 'improve_general_health',
          'allergens': <String>[],
          'dietary_exclusions': <String>[],
          'exclusion_flags': <String>[],
        },
      'pantry': pantry,
      'budget': {
        'max_total_cost': budget,
        'currency': 'EGP',
        'geography': 'Cairo',
      },
      'dietary_filters': ['budget_friendly', 'egyptian_foods'],
      'plan_preferences': {
        'meal_count': 3,
        'include_snacks': false,
        'time_horizon': 'single_day',
      },
    };
    ref
        .read(planControllerProvider.notifier)
        .run(
          (client) => client.post(
            '/v1/plans/generate',
            body,
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
  });

  final String title;
  final AsyncValue<ApiPayload>? value;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final current = value;
    if (current == null) {
      return EmptyState(title: title);
    }
    return current.when(
      data: (payload) => PayloadCard(title: title, payload: payload),
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
        subtitle: const Text('Calling FastAPI stub...'),
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
  const PayloadCard({super.key, required this.title, required this.payload});

  final String title;
  final ApiPayload payload;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final debug = ref.watch(debugModeProvider);
    final raw = payload.raw;
    final summary = summarizePayload(raw);
    final isBarcodeScan = isBarcodeScanPayload(raw);
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
              BarcodeScanResultView(raw: raw)
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
  const BarcodeScanResultView({super.key, required this.raw});

  final Map<String, Object?> raw;

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
          style: Theme.of(context).textTheme.titleLarge?.copyWith(
            fontWeight: FontWeight.w700,
          ),
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

bool isBarcodeScanPayload(Map<String, Object?> raw) {
  return raw['product_id'] != null && raw['nutrition'] is Map;
}

String nutritionBasisDisplayLabel(Object? rawNutrition) {
  if (rawNutrition is Map) {
    final explicit = text(rawNutrition['basis_label'], fallback: '').trim();
    if (explicit.isNotEmpty) {
      return explicit[0].toLowerCase() + explicit.substring(1);
    }
    final basis = text(rawNutrition['basis'], fallback: '').trim().toLowerCase();
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

  addValue(['energy_kcal', 'calories_kcal'], 'Energy', unit: 'kcal', decimals: 0);
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
  add('Meals', raw['meals']);
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
    lines.add('$label: ${formatNutritionNumber(value, decimals: decimals)} $unit');
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

bool _priceIntent(String question) {
  final normalized = question.toLowerCase();
  return [
    'cheap',
    'cheaper',
    'budget',
    'affordable',
    'cost',
    'price',
    'expensive',
    'friendly',
    'under',
    'save',
    'substitute',
    'replace',
  ].any(normalized.contains);
}

List<DropdownMenuItem<String>> options(List<String> values) {
  return [
    for (final value in values)
      DropdownMenuItem(value: value, child: Text(value.replaceAll('_', ' '))),
  ];
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

import 'package:flutter/material.dart';

/// Local test journeys. These credentials and records are demonstration data.
const demoEmail = 'dev@example.test';
const demoPassword = 'Demo123!';

Widget identifiedControl(String id, Widget child) => MergeSemantics(
  child: Semantics(identifier: id, child: child),
);

Widget identifiedText(String id, String text, {TextStyle? style}) => Semantics(
  identifier: id,
  label: text,
  excludeSemantics: true,
  child: Text(text, style: style),
);

class DemoJourneys extends StatefulWidget {
  const DemoJourneys({super.key});

  @override
  State<DemoJourneys> createState() => _DemoJourneysState();
}

class _DemoJourneysState extends State<DemoJourneys> {
  final email = TextEditingController();
  final password = TextEditingController();
  final products = <({String name, String price})>[];
  bool signedIn = false;
  String? error;
  String? notice;

  @override
  void dispose() {
    email.dispose();
    password.dispose();
    super.dispose();
  }

  void login() {
    setState(() {
      if (email.text.trim().isEmpty || password.text.isEmpty) {
        error = 'Informe e-mail e senha.';
      } else if (email.text.trim() != demoEmail ||
          password.text != demoPassword) {
        error = 'Credenciais inválidas.';
      } else {
        signedIn = true;
        error = null;
        password.clear();
      }
    });
  }

  Future<void> createProduct() async {
    final product = await Navigator.of(context)
        .push<({String name, String price})>(
          MaterialPageRoute(builder: (_) => const ProductForm()),
        );
    if (!mounted || product == null) return;
    setState(() {
      products.add(product);
      notice = 'Produto cadastrado: ${product.name}';
    });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Jornadas de teste'),
      leading: identifiedControl(
        'journeys.close',
        IconButton(
          key: const ValueKey('journeys.close'),
          tooltip: 'Voltar ao contador',
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
    ),
    body: Padding(
      padding: const EdgeInsets.all(24),
      child: signedIn ? productList(context) : loginForm(context),
    ),
  );

  Widget loginForm(BuildContext context) => ListView(
    children: [
      identifiedText(
        'login.title',
        'Login',
        style: Theme.of(context).textTheme.headlineMedium,
      ),
      const SizedBox(height: 8),
      const Text(
        'Ambiente de demonstração local.\nUse dev@example.test e Demo123!',
      ),
      const SizedBox(height: 24),
      identifiedControl(
        'login.email',
        TextField(
          key: const ValueKey('login.email'),
          controller: email,
          keyboardType: TextInputType.emailAddress,
          decoration: const InputDecoration(labelText: 'E-mail'),
        ),
      ),
      const SizedBox(height: 16),
      identifiedControl(
        'login.password',
        TextField(
          key: const ValueKey('login.password'),
          controller: password,
          obscureText: true,
          decoration: const InputDecoration(labelText: 'Senha'),
        ),
      ),
      if (error != null) ...[
        const SizedBox(height: 16),
        identifiedText(
          'login.error',
          error!,
          style: TextStyle(color: Theme.of(context).colorScheme.error),
        ),
      ],
      const SizedBox(height: 24),
      identifiedControl(
        'login.submit',
        FilledButton(
          key: const ValueKey('login.submit'),
          onPressed: login,
          child: const Text('Entrar'),
        ),
      ),
    ],
  );

  Widget productList(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      identifiedText(
        'products.title',
        'Meus produtos',
        style: Theme.of(context).textTheme.headlineMedium,
      ),
      const SizedBox(height: 8),
      const Text('Os produtos ficam em memória durante esta demonstração.'),
      const SizedBox(height: 16),
      identifiedControl(
        'products.create',
        FilledButton.icon(
          key: const ValueKey('products.create'),
          onPressed: createProduct,
          icon: const Icon(Icons.add),
          label: const Text('Cadastrar produto'),
        ),
      ),
      if (notice != null) ...[
        const SizedBox(height: 12),
        identifiedText('products.notice', notice!),
      ],
      const SizedBox(height: 16),
      Expanded(
        child: Semantics(
          identifier: 'products.list',
          label: products.isEmpty
              ? 'Nenhum produto cadastrado.'
              : products.map((p) => '${p.name}, R\$ ${p.price}').join('\n'),
          excludeSemantics: true,
          child: products.isEmpty
              ? const Center(child: Text('Nenhum produto cadastrado.'))
              : ListView(
                  children: [
                    for (final p in products)
                      Card(
                        child: ListTile(
                          title: Text(p.name),
                          subtitle: Text('R\$ ${p.price}'),
                        ),
                      ),
                  ],
                ),
        ),
      ),
      identifiedControl(
        'products.logout',
        OutlinedButton(
          key: const ValueKey('products.logout'),
          onPressed: () => setState(() {
            signedIn = false;
            notice = null;
            error = null;
            password.clear();
          }),
          child: const Text('Sair da conta'),
        ),
      ),
    ],
  );
}

class ProductForm extends StatefulWidget {
  const ProductForm({super.key});

  @override
  State<ProductForm> createState() => _ProductFormState();
}

class _ProductFormState extends State<ProductForm> {
  final name = TextEditingController();
  final price = TextEditingController();
  String? error;

  @override
  void dispose() {
    name.dispose();
    price.dispose();
    super.dispose();
  }

  void save() {
    final amount = double.tryParse(price.text.replaceAll(',', '.'));
    if (name.text.trim().isEmpty) {
      setState(() => error = 'Informe o nome do produto.');
    } else if (amount == null || !amount.isFinite || amount <= 0) {
      setState(() => error = 'Informe um preço maior que zero.');
    } else {
      Navigator.of(
        context,
      ).pop((name: name.text.trim(), price: amount.toStringAsFixed(2)));
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(
      title: const Text('Novo produto'),
      leading: identifiedControl(
        'product.cancel',
        IconButton(
          key: const ValueKey('product.cancel'),
          tooltip: 'Cancelar cadastro',
          icon: const Icon(Icons.arrow_back),
          onPressed: () => Navigator.of(context).pop(),
        ),
      ),
    ),
    body: ListView(
      padding: const EdgeInsets.all(24),
      children: [
        identifiedText(
          'product.form',
          'Cadastrar produto',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 24),
        identifiedControl(
          'product.name',
          TextField(
            key: const ValueKey('product.name'),
            controller: name,
            decoration: const InputDecoration(labelText: 'Nome do produto'),
          ),
        ),
        const SizedBox(height: 16),
        identifiedControl(
          'product.price',
          TextField(
            key: const ValueKey('product.price'),
            controller: price,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Preço'),
          ),
        ),
        if (error != null) ...[
          const SizedBox(height: 16),
          identifiedText(
            'product.error',
            error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        ],
        const SizedBox(height: 24),
        identifiedControl(
          'product.save',
          FilledButton(
            key: const ValueKey('product.save'),
            onPressed: save,
            child: const Text('Salvar produto'),
          ),
        ),
      ],
    ),
  );
}

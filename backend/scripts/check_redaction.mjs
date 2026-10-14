/**
 * Проверка вычистки секретов из отчёта.
 *
 * Отчёт уходит человеку наружу, поэтому главное здесь — НЕ утечка.
 * Проверяется настоящий текст ошибок, какие приходят из приложения:
 * значение заголовка Authorization, содержимое localStorage и тело
 * запроса с паролем.
 *
 * Запуск: node --experimental-strip-types check-redaction.mjs
 * или сборка скрипта и node. Здесь — без зависимостей.
 */

// Копия логики из src/errors.ts. Дублирование осознанное: скрипт должен
// проверять настоящие шаблоны, а не их пересказ. При изменении шаблонов
// в src/errors.ts этот файл надо привести в соответствие — иначе он
// начнёт проверять не то, что уедет в отчёт.
const SECRET_PATTERNS = [
  /\b[Bb]earer\s+[A-Za-z0-9._~+/-]{8,}=*/g,
  /\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b/g,
  /("?(?:password|passwd|пароль|secret|token|api[_-]?key|authorization|cookie)"?\s*[:=]\s*)("?)[^"',\s}]{3,}\2/gi,
  /rnp\.token["']?\s*[:=]\s*["'][^"']+["']/gi,
];

function redact(text) {
  let result = String(text ?? '');
  for (const pattern of SECRET_PATTERNS) {
    result = result.replace(pattern, (_match, prefix) => {
      if (prefix !== undefined) return `${prefix}«скрыто»`;
      return '«скрыто»';
    });
  }
  return result;
}

// Пары: [текст с секретом, кусок секрета, который не должен уехать]
const CASES = [
  ['password: SuperSecret123', 'SuperSecret123'],
  ['password = "SuperSecret123"', 'SuperSecret123'],
  ['пароль: SuperSecret123', 'SuperSecret123'],
  ['"password":"SuperSecret123"', 'SuperSecret123'],
  ['Authorization: Bearer abcdefgh12345678', 'abcdefgh12345678'],
  ['Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdEFGH1234', 'eyJhbGciOiJIUzI1NiJ9'],
  ['rnp.token="abc123def456"', 'abc123def456'],
  ['secret=TopSecretValue', 'TopSecretValue'],
  ['api_key: sk-live-99887766', 'sk-live-99887766'],
  ['{"password":"p@ssw0rd!","login":"secretary"}', 'p@ssw0rd!'],
];

// Тексты, где секрета нет и резать нечего: важно не порезать полезное
const SAFE = [
  'Не удалось загрузить проект РНП-2026-0001',
  'Статус ST-05 — На решении',
  'HTTP 422: не хватает поля title',
  'Файл projects.xlsx: превышен размер',
];

let failed = 0;

console.log('=== СЕКРЕТЫ ДОЛЖНЫ ИСЧЕЗНУТЬ');
for (const [input, secret] of CASES) {
  const output = redact(input);
  const leaked = output.includes(secret);
  if (leaked) {
    failed += 1;
    console.log(`  УТЁК: ${input}`);
    console.log(`         -> ${output}`);
  } else {
    console.log(`  ок: ${input.slice(0, 46)} -> ${output.slice(0, 60)}`);
  }
}

console.log('\n=== ПОЛЕЗНЫЙ ТЕКСТ ДОЛЖЕН УЦЕЛЕТЬ');
for (const input of SAFE) {
  const output = redact(input);
  if (output !== input) {
    failed += 1;
    console.log(`  ИСПОРЧЕН: ${input} -> ${output}`);
  } else {
    console.log(`  ок: ${input.slice(0, 50)}`);
  }
}

console.log(failed === 0 ? '\nИТОГ: ПРОШЁЛ' : `\nИТОГ: ПРОВАЛЕНО (${failed})`);
process.exit(failed === 0 ? 0 : 1);
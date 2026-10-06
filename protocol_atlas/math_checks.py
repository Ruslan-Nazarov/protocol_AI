"""Bounded exact arithmetic and polynomial identities; no eval or model code."""
import ast
from fractions import Fraction
import re


def polynomial(expression):
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 300:
        raise ValueError('Выражение должно содержать 1–300 символов.')
    expression = expression.replace('×', '*').replace('÷', '/').replace('^', '**').replace('−', '-').strip()
    tree = ast.parse(expression.strip(), mode='eval')
    if len(list(ast.walk(tree))) > 100:
        raise ValueError('Слишком большое выражение.')

    def bounded(value):
        value = {m: c for m, c in value.items() if c}
        if len(value) > 150 or any(c.numerator.bit_length() > 2048 or c.denominator.bit_length() > 2048 for c in value.values()):
            raise ValueError('Превышен предел вычисления.')
        return value

    def add(a, b, sign=1):
        result = dict(a)
        for m, c in b.items():
            result[m] = result.get(m, Fraction(0))+sign*c
        return bounded(result)

    def multiply(a, b):
        result = {}
        if len(a)*len(b) > 300:
            raise ValueError('Превышен предел произведения.')
        for ma, ca in a.items():
            for mb, cb in b.items():
                m = tuple(sorted((*ma, *mb)))
                if len(m) > 12:
                    raise ValueError('Превышен предел степени.')
                result[m] = result.get(m, Fraction(0))+ca*cb
        return bounded(result)

    def read(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            literal = ast.get_source_segment(expression, node)
            exponent = re.search(r'[eE]([+-]?\d+)', literal)
            if len(literal) > 40 or exponent and abs(int(exponent[1])) > 100:
                raise ValueError('Слишком большое число.')
            return bounded({(): Fraction(literal)})
        if isinstance(node, ast.Name) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,15}', node.id):
            return {(node.id,): Fraction(1)}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return {m: c*(-1 if isinstance(node.op, ast.USub) else 1) for m, c in read(node.operand).items()}
        if not isinstance(node, ast.BinOp):
            raise ValueError('Поддерживаются числа, переменные и арифметические операции без вызовов функций.')
        a, b = read(node.left), read(node.right)
        if isinstance(node.op, ast.Add):
            return add(a, b)
        if isinstance(node.op, ast.Sub):
            return add(a, b, -1)
        if isinstance(node.op, ast.Mult):
            return multiply(a, b)
        if isinstance(node.op, ast.Div):
            if set(b)-{()} or not b.get(()):
                raise ValueError('Деление допускается только на ненулевую числовую константу.')
            return bounded({m: c/b[()] for m, c in a.items()})
        if isinstance(node.op, ast.Pow):
            exponent = b.get((), Fraction(0))
            if set(b)-{()} or exponent.denominator != 1 or not 0 <= exponent <= 12:
                raise ValueError('Степень должна быть целой от 0 до 12.')
            if exponent == 0 and (not a or set(a)-{()}):
                raise ValueError('Нужны условия для нулевой степени.')
            result = {(): Fraction(1)}
            for _ in range(int(exponent)):
                result = multiply(result, a)
            return result
        raise ValueError('Операция не поддерживается.')
    return read(tree.body)


def check_equation(left, right):
    result = {'left': left, 'right': right, 'status': 'unknown',
              'method': 'Точные рациональные коэффициенты ограниченного многочлена',
              'scope': 'Арифметика и тождества многочленов; условия предметной применимости не устанавливаются.'}
    try:
        a, b = polynomial(left), polynomial(right)
        result['status'] = 'pass' if a == b else 'fail'
        if not (set(a) | set(b)) - {()}:
            result['computed'] = str(a.get((), Fraction(0)))
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError):
        result['detail'] = 'Выражение вне поддерживаемой области; требуется другая проверка.'
    return result


def check_prose(text):
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    # Only complete numeric equalities. Do not guess omitted quantities, units,
    # rounded answers, or symbolic assumptions from surrounding prose.
    pattern = r'(?<![\w.=])([0-9][0-9 .+*/()×÷−-]{0,100}?)\s*=\s*(-?\d+(?:\.\d+)?)(?![\d\w]|\.\d|\s*%)'
    results = []
    for match in re.finditer(pattern, text):
        left, right = match[1].strip(), match[2]
        if not re.search(r'[+*/×÷−-]', left) or match.end() < len(text) and text[match.end():].lstrip().startswith('='):
            continue
        result = check_equation(left, right)
        result.update(start=match.start(), end=match.end(), asserted=match[0])
        # Decimal approximations are not exact equalities unless explicitly
        # submitted as a calculation; avoid turning rounding into a hard failure.
        surrounding = text[max(0,match.start()-150):min(len(text),match.end()+150)]
        illustration = bool(re.search(r'неверн|ошибоч|ошибк|ложн|не\s+равн|не\s+выполня|пример|примером', surrounding, re.I))
        result['blocking'] = result['status'] == 'fail' and '.' not in left+right and not illustration
        results.append(result)
    return results

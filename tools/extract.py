"""Copy the named top-level defs (plus everything they transitively use) out of dashboard.py."""
import ast, sys
src_path, out_path = sys.argv[1], sys.argv[2]
roots = sys.argv[3].split(",")
src = open(src_path, encoding="utf-8").read()
tree = ast.parse(src)
lines = src.splitlines(keepends=True)

def defined(stmt):
    if isinstance(stmt, (ast.FunctionDef, ast.ClassDef)):
        return {stmt.name}
    names = set()
    if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        tgts = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        for t in tgts:
            for n in ast.walk(t):
                if isinstance(n, ast.Name):
                    names.add(n.id)
    return names

owners = {}
for i, st in enumerate(tree.body):
    for n in defined(st):
        owners.setdefault(n, []).append(i)

keep, todo = set(), list(roots)
seen = set()
while todo:
    name = todo.pop()
    if name in seen:
        continue
    seen.add(name)
    if name not in owners:
        print("missing:", name, file=sys.stderr)
        continue
    for i in owners[name]:
        if i in keep:
            continue
        keep.add(i)
        for n in ast.walk(tree.body[i]):
            if isinstance(n, ast.Name) and n.id in owners:
                todo.append(n.id)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in owners:
                todo.append(n.value.id)

out = ['"""Router helpers extracted from gl-e5800-dashboard (MIT). Generated -- edit app.py, not this."""\n']
for st in tree.body:
    if isinstance(st, (ast.Import, ast.ImportFrom)):
        seg = "".join(lines[st.lineno - 1:st.end_lineno])
        if "numpy" in seg:
            continue
        out.append(seg)
out.append("\n")
for i, st in enumerate(tree.body):
    if i in keep:
        start = st.lineno - 1
        if getattr(st, "decorator_list", None):
            start = st.decorator_list[0].lineno - 1
        out.append("".join(lines[start:st.end_lineno]) + "\n\n")
text = "".join(out).replace('Path("/root/dashboard")', 'Path("/root/e5ui/cache")').replace('"/root/dashboard/toggle.sh"', '"/root/e5ui/toggle.sh"')
open(out_path, "w", encoding="utf-8").write(text)
print(len(keep), "statements")

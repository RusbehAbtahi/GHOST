
# TinnyLlama Deterministic Python Debugging – Print and Direct Command Line Checks

## 1. Principle

Never "guess" or edit blindly. **Always check every assumption in code and test by printing or directly running the relevant logic.**  
A failing unit test is often due to invisible environmental or variable mismatches, not code bugs.

---

## 2. Print Internal State in Python

**Best practice:**  
Whenever a function or test depends on an environment variable, global constant, imported secret, or claim,  
**add print statements immediately before critical logic.**

### Example: Print Verification Parameters in JWT Auth

In your JWT verification function (e.g. `verify_jwt`):

```python
print("DEBUG VERIFY_JWT expects audience:", COGNITO_CLIENT_ID)
print("DEBUG VERIFY_JWT expects issuer:", COGNITO_ISSUER)
````

In your test just before building or using a token:

```python
print("DEBUG TOKEN AUD:", AUD)
print("DEBUG TOKEN ISS:", ISS)
```

**This guarantees you see mismatches in audience or issuer even if the code “looks” correct.**

---

## 3. Print Key/Cert, File Paths, and Other Critical Variables

Whenever you read key files, JWKS, or load any config, print:

```python
print("DEBUG JWKS PATH:", path)
print("DEBUG JWKS n:", pub.n)
print("DEBUG JWKS e:", pub.e)
```

Print any file existence check:

```python
print("DEBUG JWKS FILE EXISTS:", path.is_file())
```

---

## 4. Running Python Directly in Git Bash or Shell

For one-off checks, use `python` (or `py` on Windows) at the command line.

Example:
Check if a PEM file is readable and prints n/e:

```bash
py -c "from cryptography.hazmat.primitives import serialization; \
with open('02_tests/api/data/rsa_test_key.pem','rb') as f: \
    priv=serialization.load_pem_private_key(f.read(),password=None); \
    pub=priv.public_key().public_numbers(); \
    print('n:', pub.n); print('e:', pub.e)"
```

Or to print a claim from a JWT file:

```bash
py -c "from jose import jwt; print(jwt.get_unverified_claims(open('mytoken.jwt').read()))"
```

**Always use explicit paths and print full objects—never assume “should work”.**

---

## 5. Stepwise Debugging Routine

1. **Print all relevant parameters at every layer**:

   * Environment
   * Function arguments
   * File contents
   * Return values

2. **Run direct Python shell one-liners** to check file and variable state outside of test harnesses.

3. **NEVER fix the symptom without first exposing the actual difference or bug** via deterministic output.

4. **Only standardize or refactor after you confirm the exact cause** of the mismatch.

---

## 6. Example: Diagnosing JWT/Audience Mismatch

* Print key details in both signing and verifying code.
* Print claims in both token generator and verifier.
* Print paths and actual loaded file content.
* Compare printouts side by side.
* Once you see a difference, correct the code **everywhere** for consistent naming and value.
* Rerun, and confirm by output.

---

## 7. Golden Rule

> If you can’t see it in a print/log/shell output, **you do not know** what value your code is really using.

**Always expose reality before you “fix” anything.**

---

## 8. Extra: Print Full Objects for Complex Types

For claims, dicts, lists:

```python
import pprint
pprint.pprint(my_dict)
```

For base64, decode and print:

```python
import base64
print(base64.urlsafe_b64decode(jwk['n'] + '=='))
```

---

## 9. Commit Clean Code, Remove Debug Prints

**After fixing, remove all print/debug lines** before merging or releasing.

---

## 10. Use This as a Template

Copy this file to `docs/Debugging_Best_Practices.md`
Update with new lessons and deterministic recipes as your project grows.

---

**This approach will save you and your team hours of frustration, every time.**

```

---


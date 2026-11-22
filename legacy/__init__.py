"""The competition-era search, kept because its negative result is still cited.

Nothing here is used by the current testbed. `mgcg/deploy` and `mgcg/attacks` take the protocol
layer from `mgcg.runtime` and never import this package, which is the point of the split: the
deployment stack used to pull in families, verification and the old filters just to read one
JSON call.

It stays for two reasons.

First, a result recorded in the README would otherwise be unreproducible: this search lowers the
teacher-forced likelihood of a target call from 2.16 to 1.09 nats while the model's behaviour
does not change once. That gap is the evidence behind the claim that a likelihood, and later a
judge margin, is a proxy and not the objective.

Second, two findings are still cited: one soft hyphen inside a word moves a keyword filter in
66 of 308 single insertions, and an invisible-only vocabulary is what the CW section rules out
for the judge.
"""

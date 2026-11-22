"""A deployment-shaped testbed for an assistant's input and output guards.

Modules:
    model     target model loading, shared by the testbed and the attack surface
    runtime   one assistant turn: generate, parse a tool call, retry once
    deploy    the mailbox world, the three guards, the episode, the two axes, the CLI
    attacks   white-box attacks on the judge, on one shared scoring surface

The competition-era search that gave this project its name lives in `legacy/`, outside this
package. Nothing here imports it: the split exists so the testbed cannot accidentally inherit
four attack families and a predicated verifier it does not use.
"""

__all__ = ["model", "runtime", "deploy", "attacks"]

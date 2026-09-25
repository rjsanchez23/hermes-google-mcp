# Terms of Service

**Last updated:** 2026-09-25

These terms cover **"Hermes Pi5"**, the OAuth client published from this repository.

## 1. Nature of the service

This is a self-hosted, single-user software tool. It is not a hosted service. There is no
account registration, no subscription, no service level agreement and no support commitment.
You run it on hardware you control.

By authorizing this client you are authorizing **your own** local copy of the software to act
on **your own** Google account, within the scopes listed in the Privacy Policy.

## 2. Authorization and revocation

Authorization happens through Google's standard OAuth flow. You grant scopes on Google's
consent screen and can revoke them at any time at <https://myaccount.google.com/permissions>
or by deleting the OAuth client in Google Cloud.

Revocation is immediate and requires no notice. Re-authorizing after revocation starts from
scratch.

## 3. Acceptable use

This client is intended for personal, non-commercial automation of an account you own.

You agree not to use it to:

- access an account you do not own or are not authorized to administer
- send unsolicited bulk mail, or mail on behalf of third parties without their consent
- circumvent Google's abuse controls, rate limits or anti-spam systems
- violate any applicable law, or Google's Terms of Service and API Terms

Google's own API Terms of Service and Acceptable Use Policy apply to every call this client
makes, and take precedence over these terms.

## 4. No warranty

The software is provided **"as is", without warranty of any kind**, express or implied,
including but not limited to the warranties of merchantability, fitness for a particular
purpose and non-infringement.

In particular, there is **no guarantee of correctness, availability or fitness for any
particular use**. Do not rely on it for anything where a failure could cause you harm.

## 5. Limitation of liability

To the maximum extent permitted by law, the author shall not be liable for any indirect,
incidental, special, consequential or punitive damages, or for any loss of data, loss of
profits, loss of goodwill, or loss of access to your Google account, arising out of or in
connection with the software or its use, whether in contract, tort or otherwise, even if
advised of the possibility of such damages.

Because the software is typically run by the same person who operates the Google account it
acts on, you are ordinarily both the operator and the only person affected; these terms
matter mainly if you redistribute the software or expose it to others.

## 6. Irreversible operations

Certain operations cannot be undone: sending an email, deleting a calendar event, and
emptying the trash. The software marks irreversible tools in its MCP catalogue and
prioritises drafts over sending for that reason, but **this reduces risk without eliminating
it**.

You are responsible for reviewing what your agent proposes before it acts, and for any
consequence of an action you approve. Google provides a 30-day trash recovery window for
messages moved to trash, which is not a guarantee and depends on your account settings.

## 7. Automated action and third-party content

The software exists to let a language model act on your behalf. The model may misread
instructions, hallucinate, or act on text embedded in content it reads — a technique known as
prompt injection, in which a third party writes instructions inside an email or a calendar
invitation hoping the agent obeys them.

You accept this risk. Mitigations provided by the software (read-only Drive, drafts over
send, requiring confirmation for destructive tools) are best-effort and not a guarantee.

## 8. Termination

You may stop using the software and revoke access at any time, without notice. No
termination procedure exists because there is no relationship to terminate.

## 9. Changes

No warranty is offered that these terms will be updated. The authoritative version is the
one in the repository at the time you installed the software.

## 10. Contact

Ricardo Sánchez Estévez — <rjsemaga@gmail.com>

## 11. Spanish version (informative)

For convenience, the substance of these terms in Spanish:

Este software se distribuye tal cual, sin garantía de ningún tipo. El usuario autoriza a su
propia copia local a actuar sobre su propia cuenta de Google dentro de los ámbito de
permisos indicados en la Política de Privacidad, y puede revocar esa autorización en
cualquier momento. Las acciones irreversibles (enviar correo, eliminar eventos) no se pueden
deshacer. Al conceder acceso a un modelo de lenguaje existe el riesgo de que actúe sobre
contenido de terceros que imite instrucciones; las mitigaciones incluidas reducen ese riesgo
sin eliminarlo.

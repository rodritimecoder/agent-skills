---
description: Lane agent — can read, edit and run tests, cannot push, delete or sudo
mode: primary
permissions:
  - action: shell
    resource: "git push*"
    effect: deny
  - action: shell
    resource: "rm -rf*"
    effect: deny
  - action: shell
    resource: "sudo*"
    effect: deny
  - action: shell
    resource: "git reset --hard*"
    effect: deny
---
You are a lane agent. You may read, edit and run tests. You may not push, delete, or use sudo.

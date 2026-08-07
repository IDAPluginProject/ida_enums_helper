# IDA Enums Helper Plugin

![logo](logo.jpg)

The IDA Enums Helper Plugin is a tool designed to streamline enum management within IDA Pro. It introduces three key actions to enhance your workflow:

- **Rename Enum Member**: Quickly rename an enum member. *(Hotkey: N)*
- **Add to Enum**: Add a number, or a whole variable's worth of constants, to an existing or new enum. *(Hotkey: A)*
- **Add to the Last Used Enum**: The same, straight into the most recently used enum. *(Hotkey: Shift-A)*

These actions are also accessible via the context menu in the pseudocode view.

## What gets collected

One constant is rarely the whole story, so pressing `A` on a number does not look at
that number alone. The plugin finds the variable the number belongs to, then everything
in the current function that variable is copied to or from, and offers the constants of
the whole group at once:

```c
int cmd = 7;             //  <- press A here
state = cmd;             //  state joins cmd
if (state == 0xFFFFFFFF) //  0xFFFFFFFF joins in
  return 0;
switch (state) {         //  and every case of the switch
  case 0: ...
  case 4: ...
}
```

Members are collected from assignments, from `==` and `!=`, and from every case of a
`switch`. Locals, globals and structure fields all count, so a group can reach across
`cfg->mode` and `g_state` as easily as across `v5`. Only plain integers are followed:
a copied pointer is an ordinary assignment too, and following those would tie together
everything the function moves around.

The cursor does not have to be on a number at all — press `A` on `cmd` itself, on its
declaration, or on `cfg->mode`, and the same group is collected. There is nothing to
reformat then, so that only adds the members and retypes the group.

Ordered comparisons are left out on purpose — `if (cmd > 5)` states a bound, not a
member worth naming. Bitwise sources (`|=`, `&`) are off as well; set `COLLECT_BITWISE`
in the source if you work with flag enums.

Every constant is masked to the width of what holds it, so `state == -1` becomes
`0xFFFFFFFF` rather than a twenty-digit number, and a new enum is created as wide as
that variable.

## Naming and retyping

All the names are asked for before anything is added, in one editable list:

```
// 3 new members of CMD_KIND
// retyped to it: cmd, config_t::mode, state
// delete a line to skip that value
0x0 = val_0
0x7 = CMD_UPLOAD
0xffffffff = val_FFFFFFFF
```

Delete a line to leave that value out; hex and decimal both parse. If a name turns out
to be taken by another enum, the box reopens with the reason and nothing you typed is
lost — the enum is either filled completely or left as it was.

Afterwards every variable in the group of matching size is retyped to the enum, which is
what the header of that list is telling you. Anything of a different size is left alone
and mentioned in the log, since widening a structure member would move whatever follows
it.

### Compatibility
- Tested with IDA Pro 9.4 on macOS.
- Expected to work on Windows and Linux as well.

### Known Issues
- **Cached Decompiled Code**: Changes made by renaming or adding enum members are not stored in the cached decompiled code. To view the updates, refresh the pseudocode view by pressing `F5`. This issue only occurs if you restart IDA and reopen the same file; otherwise, changes are visible immediately.
- **Wide Groups**: A long chain of integer assignments makes a large group, and dispatcher-style code has plenty. The group is listed before anything is changed, so cancel the naming dialog if it reaches further than you meant.
- **Enum Member Renaming in `switch` Statements**: Renaming enum members used in `switch` cases is not currently supported. This is a limitation of IDA Pro itself.

## Installation
To install the IDA Enums Helper Plugin, follow these steps:

1. Ensure that IDA Pro is installed on your system.
2. Clone or download this repository.
3. Copy the `enums_helper.py` file into the `plugins` directory of your IDA Pro installation.

For further assistance or to report issues, please refer to the repository's issue tracker.
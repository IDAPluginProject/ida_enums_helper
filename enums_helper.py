"""
Author: Milankovo, 2025
License: MIT
"""

import logging

import idaapi

logger = logging.getLogger("EnumsHelper")
logger.setLevel(logging.INFO)


NETNODE_NAME = "$ enums_helper"
last_enum_used: str | None = None

# Bitwise sources (|=, &=, x & const) matter for flag enums but are by far the
# noisiest, so they stay out until asked for.
COLLECT_BITWISE = False


def hexnum(v: int) -> str:
    """A constant the way it reads best: small ones decimal, the rest hex."""
    return str(v) if -10 < v < 10 else f"{v:#x}"


class EnumChooser(idaapi.Choose):
    def __init__(self, title="Please choose enum", values: list[int] | None = None):
        self.values = values or []
        super().__init__(
            title,
            cols=[
                ["#name of the enum#Enumeration", idaapi.Choose.CHCOL_PLAIN | 30],
                [
                    "#Matching members already present in the enum#Members",
                    idaapi.Choose.CHCOL_PLAIN | 20,
                ],
                [
                    "#List of numbers that will be added to the enum#Missing",
                    idaapi.Choose.CHCOL_PLAIN | 30,
                ],
                ["#number of matching members#matching", idaapi.Choose.CHCOL_DEC | 5],
                ["#number of missing members#missing", idaapi.Choose.CHCOL_DEC | 5],
            ],
            flags=idaapi.Choose.CH_MODAL,
        )
        self.items = self._get_enum_list()

    def _get_enum_list(self):
        enums = [("<NEW>", "", "", "", "")]

        for i in range(1, idaapi.get_ordinal_limit()):
            if not idaapi.is_type_choosable(None, i):  # type: ignore
                continue

            try:
                t = idaapi.tinfo_t(ordinal=i)
            except ValueError:
                continue
            if not t.is_enum():
                continue
            name = t.get_type_name()
            if not name:
                logger.debug(f"Skipping unnamed enum with ordinal {i}: {t.dstr()}")
                continue

            members = []
            missing = []
            for value in self.values:
                idx, item = t.get_edm_by_value(value)
                if idx != -1:
                    members.append(f"{hexnum(value)}={item.name}")
                else:
                    missing.append(hexnum(value))

            members = sorted(set(members))

            members_str = ", ".join(members)
            missing_str = ", ".join(missing)

            enums.append(
                (name, members_str, missing_str, str(len(members)), str(len(missing)))
            )
        return enums

    def OnGetSize(self):
        return len(self.items)

    def OnGetLine(self, n):
        return self.items[n]

    def OnSelectLine(self, n):
        return self.items[n][0]

    def OnRefresh(self, n):
        self.items = self._get_enum_list()
        # None asks for the standard refresh; the callback is documented to
        # answer with (changed, selection), never with a count.


def named_type(name: str | None) -> idaapi.tinfo_t | None:
    """Look up a named type, answering None instead of raising.

    tinfo_t(name=...) raises ValueError on an empty name and on one that has
    since been deleted, and this runs inside update() where an exception would
    surface on every popup.
    """
    if not name:
        return None
    try:
        return idaapi.tinfo_t(name=name)
    except ValueError:
        return None


def enum_by_name(name: str | None) -> idaapi.tinfo_t | None:
    ti = named_type(name)
    return ti if ti is not None and ti.is_enum() else None


def ask_new_enum(width: int = 0) -> idaapi.tinfo_t | None:
    """Create an enum as wide as whatever is going to hold it.

    Left unspecified, an enum takes the size of its widest member, so a masked
    sentinel such as 0xFFFFFFFF would quietly make it eight bytes wide and stop
    it fitting the four-byte variable it was collected from.
    """
    new_enum_name = idaapi.ask_ident("", "Enter new enum name:")
    if not new_enum_name:
        logger.warning("No name provided for the new enumeration. Operation aborted.")
        return None

    if width not in (1, 2, 4, 8):
        width = 0

    tid = idaapi.create_enum_type(
        new_enum_name, idaapi.enum_type_data_t(), width, idaapi.no_sign, False
    )
    if tid == idaapi.BADADDR:
        logger.error(
            f"Error: Unable to create a new enumeration named '{new_enum_name}'."
        )
        return None

    return idaapi.tinfo_t(tid=tid)


def choose_or_create_enum(values: list[int], width: int = 0) -> idaapi.tinfo_t | None:
    chooser = EnumChooser(
        values=values,
        title="Please choose enum",
    )
    selected = chooser.Show(modal=True)
    if selected < 0:
        return None

    selected_enum_name = chooser.items[selected][0]
    if selected_enum_name == "<NEW>":
        return ask_new_enum(width)

    ti = enum_by_name(selected_enum_name)
    if ti is None:
        logger.error(f"Error: enumeration '{selected_enum_name}' is gone.")
    return ti


class base_action_handler_t(idaapi.action_handler_t):
    action_name: str
    action_label: str
    action_shortcut: str

    @classmethod
    def register(cls: type["base_action_handler_t"]):
        action = idaapi.action_desc_t(
            cls.action_name, cls.action_label, cls(), cls.action_shortcut
        )
        idaapi.register_action(action)

    @classmethod
    def unregister(cls: type["base_action_handler_t"]):
        idaapi.unregister_action(cls.action_name)

    @classmethod
    def register_actions(cls: type["base_action_handler_t"]):
        for action in cls.__subclasses__():
            action.register()

    @classmethod
    def unregister_actions(cls: type["base_action_handler_t"]):
        for action in cls.__subclasses__():
            action.unregister()


def numform_opnum(nf: idaapi.number_format_t) -> int:
    # very annoying idapython feature/bug: hexrays.hpp items with type 'char' are mapped to 'str' instead of 'int'
    # so we need to convert it back to int
    opnum = nf.opnum
    if isinstance(opnum, str):
        return ord(opnum)
    return opnum


def update_number_format_with_enum_name(nf: idaapi.number_format_t, enum_name: str):
    shift = idaapi.get_operand_type_shift(numform_opnum(nf))
    mask = 0xF << shift
    enum = 0x8 << shift
    nf.flags = (nf.flags & ~mask) | enum
    nf.type_name = enum_name


def dump_user_numforms(vu):
    for f, s in vu.cfunc.numforms.items():
        logger.info(
            f"found user numform ({f.ea:x}, {f.opnum}) "
            f"({numform_opnum(s)}, {s.flags:x}, {s.type_name})"
        )


def update_number_formats(
    cfunc: idaapi.cfuncptr_t, ea: int, nf: idaapi.number_format_t
):
    loc = idaapi.operand_locator_t(ea, numform_opnum(nf))

    if loc in cfunc.numforms:  # type: ignore
        del cfunc.numforms[loc]  # type: ignore
    cfunc.numforms[loc] = nf  # type: ignore

    cfunc.save_user_numforms()


def default_member_name(v: int) -> str:
    return f"val_{v}" if v < 0x10 else f"val_{v:X}"


def missing_values(ti: idaapi.tinfo_t, values: list[int]) -> list[int]:
    """The values the enum does not describe yet."""
    missing = []
    for v in values:
        idx, edm = ti.get_edm_by_value(v)
        if idx != -1:
            logger.debug(f"{hexnum(v)} is already '{edm.name}'.")
            continue
        missing.append(v)
    return missing


def parse_member_names(text: str) -> dict[int, str]:
    """The `value = name` pairs of the naming dialog.

    Comments and blank lines are ignored, which is how a deleted or commented
    out line skips its value.
    """
    names: dict[int, str] = {}
    for line in text.splitlines():
        line = line.split("//", 1)[0].strip()
        if not line:
            continue
        text_value, sep, name = line.partition("=")
        name = name.strip()
        try:
            v = int(text_value.strip(), 0)
        except ValueError:
            logger.warning(f"Ignoring '{line}': that is not a value.")
            continue
        if not sep or not name:
            logger.warning(f"Ignoring '{line}': no name given.")
            continue
        names[v] = name
    return names


def ask_member_names(
    ti: idaapi.tinfo_t,
    values: list[int],
    carriers: list["carrier_t"],
    complaint: str = "",
) -> dict[int, str] | None:
    """Names for every value about to be added, decided before any is.

    Asking for all of them up front is what keeps a cancelled run from leaving
    half the members behind, and it matters more now that a single run can turn
    up a dozen values.
    """
    enum_name = ti.get_type_name()

    if len(values) == 1:
        prompt = f"Name for new enum member of {enum_name}"
        if len(carriers) > 1:
            prompt += f" ({len(carriers)} variables will be retyped)"
        name = idaapi.ask_ident(default_member_name(values[0]), prompt)
        if not name:
            return None
        return {values[0]: name}

    lines = [f"// {len(values)} new members of {enum_name}"]
    if complaint:
        lines.append(f"// {complaint}")
    if len(carriers) > 1:
        lines.append("// retyped to it: " + ", ".join(c.label for c in carriers))
    lines.append("// delete a line to skip that value")
    lines += [f"{v:#x} = {default_member_name(v)}" for v in values]

    text = idaapi.ask_text(0, "\n".join(lines), f"New members of {enum_name}")
    if text is None:
        return None
    return parse_member_names(text)


def add_enum_members(ti: idaapi.tinfo_t, names: dict[int, str]) -> str:
    """Add the named values, all of them or none.

    A name already used elsewhere is refused by add_edm alone, so the ones that
    went in before it are taken back out again: a half-populated enum is worse
    than none of it, and the caller gets to ask for the names once more.
    """
    added = []
    for v, name in sorted(names.items()):
        try:
            ti.add_edm(name, v)
        except ValueError as e:
            for done in added:
                ti.del_edm(done)
            reason = str(e)
            if "name is used in another enum" in reason:
                return f"'{name}' is used in another enum, pick another name."
            return f"cannot add {name} = {hexnum(v)}: {reason}"
        added.append(name)
    return ""


def name_and_add_members(
    ti: idaapi.tinfo_t, values: list[int], carriers: list["carrier_t"]
) -> bool:
    """Name and add every value the enum is missing."""
    missing = missing_values(ti, values)
    if not missing:
        logger.info(f"{ti.get_type_name()} already describes all the values.")
        return True

    complaint = ""
    while True:
        names = ask_member_names(ti, missing, carriers, complaint)
        if not names:
            logger.warning("No names given for the new enum members; nothing added.")
            return False

        complaint = add_enum_members(ti, names)
        if not complaint:
            logger.info(
                f"Added {len(names)} member(s) to {ti.get_type_name()}: "
                + ", ".join(f"{name} = {hexnum(v)}" for v, name in sorted(names.items()))
            )
            return True
        logger.warning(complaint)


def switch_has_cases_not_covered_by_enum(citem: idaapi.ctree_item_t) -> bool:
    switch = citem_to_switch(citem)
    if switch is None:
        return False

    ti = enum_by_name(switch.mvnf.nf.type_name)
    if ti is None:
        return True

    for case in switch.cases:
        for v in case.values:
            idx, edm = ti.get_edm_by_value(v)
            if idx == -1:
                return True
    return False


def current_number(vu: idaapi.vdui_t) -> idaapi.cnumber_t | None:
    """The number under the cursor, if the cursor is on one at all.

    get_number() is only meaningful for a ctree item, and the cursor may well
    be on a variable declaration or past the end of the line.
    """
    return vu.get_number() if vu.item.is_citem() else None


def can_add_to_enum(ctx: idaapi.action_ctx_base_t):
    """Is there anything here to put in an enum?

    A number, of course, but a variable will do as well: it names the group
    whose constants would be collected anyway, so there is no reason to make
    somebody find one of those constants first.
    """
    if ctx.widget_type != idaapi.BWN_PSEUDOCODE:
        return idaapi.AST_DISABLE_FOR_WIDGET

    vu: idaapi.vdui_t = idaapi.get_widget_vdui(ctx.widget)
    if vu is None:
        return idaapi.AST_DISABLE

    vu.get_current_item(idaapi.USE_KEYBOARD)

    logger.debug(f"item {vu.item.citype}")
    if vu.item.citype == idaapi.VDI_EXPR:
        logger.debug(f"{vu.item.it.ea=:#x} {vu.item.it.to_specific_type.opname}")  # type: ignore
    logger.debug(f"tail {vu.tail.dstr()}")
    logger.debug(f"tail.citype {vu.tail.citype}")
    if vu.tail.citype == idaapi.VDI_TAIL:
        logger.debug(f"{vu.tail.loc.ea=:#x} {vu.tail.loc.itp=:#x}")

    num = current_number(vu)
    if num is None:
        # Nothing to reformat, so this only collects the group and retypes it.
        return idaapi.AST_ENABLE if seed_carrier(vu) is not None else idaapi.AST_DISABLE

    if num.nf.is_enum() and not switch_has_cases_not_covered_by_enum(vu.item):
        return idaapi.AST_DISABLE

    return idaapi.AST_ENABLE


def update_cnumber(num: idaapi.cnumber_t, ti: idaapi.tinfo_t, vu: idaapi.vdui_t):
    update_number_format_with_enum_name(num.nf, ti.get_type_name())

    citem: idaapi.ctree_item_t = vu.item
    if not citem.is_citem():  # tail, etc.
        logger.debug("Not a citem")
        return

    it = citem.it

    citem_ea = citem.get_ea()
    if citem_ea != it.ea:
        logger.warning(
            f"inconsistent ea between citem.get_ea()={citem_ea:x} and citem.it.ea={it.ea:x} for {it.to_specific_type.opname}"  # type: ignore
        )

    update_number_formats(vu.cfunc, it.ea, num.nf)
    if it.is_expr():
        citem.e.type = ti

    vu.cfunc.refresh_func_ctext()


def citem_to_switch(citem: idaapi.ctree_item_t) -> idaapi.cswitch_t | None:
    if not citem.is_citem():
        return None

    if citem.it.op != idaapi.cit_switch:
        return None

    switch = citem.it.to_specific_type.cswitch  # type: ignore
    return switch


def strip_casts(e: idaapi.cexpr_t) -> idaapi.cexpr_t:
    """What is underneath the casts, which never change what is named."""
    while e.op == idaapi.cot_cast:
        e = e.x
    return e


def mask_value(v: int, size: int) -> int:
    """A constant the way its carrier holds it.

    Numbers arrive from the ctree as unsigned 64-bit, so `state == -1` shows up
    as 0xFFFFFFFFFFFFFFFF and would be refused by a four-byte enum.
    """
    if size <= 0 or size >= 8:
        return v & 0xFFFFFFFFFFFFFFFF
    return v & ((1 << (size * 8)) - 1)


class carrier_t:
    """Something that can hold the enum: a local, a global, or a struct field.

    The key identifies it across the whole ctree, so every node naming the same
    variable answers the same key and joins the same class.
    """

    def __init__(self, key: tuple, label: str, size: int):
        self.key = key
        self.label = label
        self.size = size

    def __repr__(self):
        return f"<carrier {self.label}, {self.size} bytes>"

    def retype(self, vu: idaapi.vdui_t, ti: idaapi.tinfo_t) -> bool:
        raise NotImplementedError


class lvar_carrier_t(carrier_t):
    """A local variable, looked up again by name.

    Retyping one local re-decompiles the function, so the index this was found
    at may not mean the same variable by the time the next one is retyped. The
    name does, being unique within a function.
    """

    def retype(self, vu, ti):
        for lvar in vu.cfunc.get_lvars():
            if lvar.name == self.label:
                return vu.set_lvar_type(lvar, ti)
        logger.warning(f"Local variable '{self.label}' is gone; not retyped.")
        return False


class global_carrier_t(carrier_t):
    def __init__(self, key: tuple, label: str, size: int, ea: int):
        super().__init__(key, label, size)
        self.ea = ea

    def retype(self, vu, ti):
        return idaapi.apply_tinfo(self.ea, ti, idaapi.TINFO_DEFINITE)


class field_carrier_t(carrier_t):
    """A structure member, addressed by its owner's name and its own offset.

    The owner has to be fetched from the type library again before it is
    changed: the type hanging off a ctree node is a copy, and editing that
    changes nothing anybody else will see.
    """

    def __init__(self, key: tuple, label: str, size: int, owner: str, offset: int):
        super().__init__(key, label, size)
        self.owner = owner
        self.offset = offset

    def retype(self, vu, ti):
        owner = named_type(self.owner)
        if owner is None:
            logger.warning(f"Structure '{self.owner}' is gone; {self.label} not retyped.")
            return False
        idx, _udm = owner.get_udm_by_offset(self.offset * 8)
        if idx == -1:
            logger.warning(f"{self.label} is gone; not retyped.")
            return False
        code = owner.set_udm_type(idx, ti)
        if code != idaapi.TERR_OK:
            logger.error(
                f"Error: cannot retype {self.label}: {idaapi.tinfo_errstr(code)}"
            )
            return False
        return True


def can_hold_enum(t: idaapi.tinfo_t) -> bool:
    """Could this type be an enum?

    Only a plain integer could. Keeping pointers, arrays and structures out is
    what stops one class from swallowing the next: a pointer copied from one
    variable to another is a perfectly ordinary assignment, and following it
    would tie together everything the function ever moves around.
    """
    if t is None or t.empty():
        return False
    if t.is_ptr() or t.is_array() or t.is_udt() or t.is_floating() or t.is_func():
        return False
    if not (t.is_integral() or t.is_enum() or t.is_bool()):
        return False
    return t.get_size() in (1, 2, 4, 8)


def lvar_carrier(idx: int, lvar: idaapi.lvar_t) -> carrier_t | None:
    if not can_hold_enum(lvar.type()):
        return None
    return lvar_carrier_t(("lvar", idx), lvar.name, lvar.width)


def carrier_of_lvar(cfunc: idaapi.cfuncptr_t, lvar: idaapi.lvar_t) -> carrier_t | None:
    """The carrier for a variable the cursor names rather than an expression.

    The cursor reports a variable without saying which index it is, and names
    are unique within a function, so that is what finds it again.
    """
    lvars = cfunc.get_lvars()
    for idx in range(lvars.size()):
        if lvars[idx].name == lvar.name:
            return lvar_carrier(idx, lvars[idx])
    return None


def make_carrier(cfunc: idaapi.cfuncptr_t, e: idaapi.cexpr_t) -> carrier_t | None:
    """The carrier an expression names, or None when it names none.

    Whatever could not be retyped afterwards is not a carrier: a call result, a
    sum, a member of a structure with no name of its own.
    """
    e = strip_casts(e)

    if e.op == idaapi.cot_var:
        lvars = cfunc.get_lvars()
        if e.v.idx >= lvars.size():
            return None
        return lvar_carrier(e.v.idx, lvars[e.v.idx])

    if e.op == idaapi.cot_obj:
        if not can_hold_enum(e.type):
            return None
        label = idaapi.get_name(e.obj_ea) or f"{e.obj_ea:#x}"
        return global_carrier_t(
            ("obj", e.obj_ea), label, e.type.get_size(), e.obj_ea
        )

    if e.op in (idaapi.cot_memptr, idaapi.cot_memref):
        owner = e.x.type
        if owner.is_ptr():
            owner = owner.get_pointed_object()
        name = owner.get_type_name()
        if not name:
            return None
        idx, udm = owner.get_udm_by_offset(e.m * 8)
        if idx == -1 or udm.offset != e.m * 8:
            return None
        if not can_hold_enum(udm.type):
            return None
        return field_carrier_t(
            ("field", name, e.m), f"{name}::{udm.name}", udm.size // 8, name, e.m
        )

    return None


class carrier_classes_t:
    """Carriers grouped by the code that copies one into another.

    A constant seen anywhere in a class describes every carrier in it, which is
    the whole point: `cmd = 7` in one place and `switch (state)` in another
    describe the same set of names once `state = cmd` ties them together.
    """

    def __init__(self):
        self.parents: dict[tuple, tuple] = {}
        self.carriers: dict[tuple, carrier_t] = {}
        self.values: dict[tuple, set[int]] = {}

    def add(self, carrier: carrier_t) -> tuple:
        self.parents.setdefault(carrier.key, carrier.key)
        self.carriers.setdefault(carrier.key, carrier)
        return carrier.key

    def find(self, key: tuple) -> tuple:
        root = key
        while self.parents[root] != root:
            root = self.parents[root]
        while self.parents[key] != root:
            self.parents[key], key = root, self.parents[key]
        return root

    def union(self, a: tuple, b: tuple):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parents[rb] = ra

    def note_value(self, key: tuple, v: int):
        self.values.setdefault(key, set()).add(mask_value(v, self.carriers[key].size))

    def collect(self, key: tuple) -> tuple[list[carrier_t], set[int]]:
        """Everything tied to one carrier: the others, and their constants."""
        if key not in self.parents:
            return [], set()

        root = self.find(key)
        carriers: list[carrier_t] = []
        values: set[int] = set()
        for other in self.parents:
            if self.find(other) != root:
                continue
            carriers.append(self.carriers[other])
            values |= self.values.get(other, set())
        carriers.sort(key=lambda c: c.label)
        return carriers, values


EQUALITY_OPS = (idaapi.cot_eq, idaapi.cot_ne)

# An assignment or a test that only sets or clears bits says nothing about the
# whole value, so these are read for constants but never tie two carriers.
BITWISE_OPS = (
    idaapi.cot_asgbor,
    idaapi.cot_asgband,
    idaapi.cot_asgxor,
    idaapi.cot_bor,
    idaapi.cot_band,
    idaapi.cot_xor,
)


class relation_collector_t(idaapi.ctree_visitor_t):
    """One walk of the function gathering both the classes and the constants.

    Ordered comparisons are deliberately left out: `if (cmd > 5)` states a
    bound, not a member worth naming.
    """

    def __init__(self, cfunc: idaapi.cfuncptr_t):
        idaapi.ctree_visitor_t.__init__(self, idaapi.CV_FAST)
        self.cfunc = cfunc
        self.classes = carrier_classes_t()

    def carrier(self, e: idaapi.cexpr_t) -> tuple | None:
        carrier = make_carrier(self.cfunc, e)
        return self.classes.add(carrier) if carrier is not None else None

    def relate(self, target: idaapi.cexpr_t, source: idaapi.cexpr_t, tie=True):
        """Read what the code puts on the two sides of an = or an ==."""
        key = self.carrier(target)
        if key is None:
            return

        source = strip_casts(source)
        if source.op == idaapi.cot_num:
            self.classes.note_value(key, source.numval())
            return
        if not tie:
            return
        other = self.carrier(source)
        if other is not None:
            self.classes.union(key, other)

    def visit_expr(self, e: idaapi.cexpr_t):
        if e.op == idaapi.cot_asg:
            self.relate(e.x, e.y)
        elif e.op in EQUALITY_OPS:
            # A comparison has no preferred side, so read it both ways round.
            self.relate(e.x, e.y)
            self.relate(e.y, e.x)
        elif COLLECT_BITWISE and e.op in BITWISE_OPS:
            self.relate(e.x, e.y, tie=False)
            self.relate(e.y, e.x, tie=False)
        return 0

    def visit_insn(self, i: idaapi.cinsn_t):
        if i.op != idaapi.cit_switch:
            return 0

        switch = i.cswitch
        key = self.carrier(switch.expr)
        if key is None:
            return 0

        case: idaapi.ccase_t
        for case in switch.cases:
            for v in case.values:
                self.classes.note_value(key, v)
        return 0


def carrier_of_number(cfunc: idaapi.cfuncptr_t, num: idaapi.cexpr_t) -> carrier_t | None:
    """What a number is being assigned to or compared against."""
    # Up through the casts wrapping the number to whatever holds it.
    parent = cfunc.body.find_parent_of(num)
    while parent is not None and parent.op == idaapi.cot_cast:
        parent = cfunc.body.find_parent_of(parent)
    if parent is None:
        return None
    if parent.op != idaapi.cot_asg and parent.op not in EQUALITY_OPS:
        return None

    # The side that is not the number, whichever side that is. Asking which one
    # holds our own node is not possible: two ctree wrappers around the same
    # item are different Python objects.
    left, right = strip_casts(parent.cexpr.x), strip_casts(parent.cexpr.y)
    if right.op == idaapi.cot_num:
        return make_carrier(cfunc, left)
    if left.op == idaapi.cot_num:
        return make_carrier(cfunc, right)
    return None


def seed_carrier(vu: idaapi.vdui_t) -> carrier_t | None:
    """The carrier the cursor is talking about.

    A switch names its selector, a number names whatever it is assigned to or
    compared against, and the cursor may of course sit on the carrier itself.
    """
    cfunc = vu.cfunc

    switch = citem_to_switch(vu.item)
    if switch is not None:
        return make_carrier(cfunc, switch.expr)

    # A variable is reported as itself, not as an expression, when the cursor
    # is on its declaration.
    lvar = vu.item.get_lvar()
    if lvar is not None:
        return carrier_of_lvar(cfunc, lvar)

    if not vu.item.is_citem() or not vu.item.it.is_expr():
        return None

    item: idaapi.cexpr_t = vu.item.e
    direct = make_carrier(cfunc, item)
    if direct is not None:
        return direct
    if item.op != idaapi.cot_num:
        return None

    return carrier_of_number(cfunc, item)


class collection_t:
    """What the cursor turned up: values to name, carriers to retype."""

    def __init__(
        self,
        values: list[int],
        carriers: list[carrier_t],
        seed: carrier_t | None = None,
    ):
        self.values = values
        self.carriers = carriers
        self.seed = seed

    @property
    def width(self) -> int:
        return self.seed.size if self.seed is not None else 0

    def describe(self) -> str:
        return (
            f"{', '.join(hexnum(v) for v in self.values) or 'no values'} "
            f"from {', '.join(c.label for c in self.carriers) or 'nothing in particular'}"
        )


def gather_values(vu: idaapi.vdui_t) -> collection_t:
    """Every constant that belongs with the one under the cursor.

    The cursor points at one number, but the enum it wants is described by the
    whole class of variables that number travels through: what it is assigned
    to, what that is compared against, and every case of a switch on any of
    them.
    """
    num = current_number(vu)
    seed = seed_carrier(vu)

    values: set[int] = set()
    carriers: list[carrier_t] = []

    if seed is not None:
        collector = relation_collector_t(vu.cfunc)
        collector.apply_to(vu.cfunc.body, None)
        collector.classes.add(seed)
        carriers, values = collector.classes.collect(seed.key)

    if num is not None:
        values.add(mask_value(num._value, seed.size if seed is not None else 0))

    return collection_t(sorted(values), carriers, seed)


def retype_carriers(vu: idaapi.vdui_t, ti: idaapi.tinfo_t, carriers: list[carrier_t]):
    """Give the enum to everything in the class that is the right size.

    A carrier of another size is left alone: widening a structure member or a
    global would move whatever follows it, which is not what naming a constant
    asked for.
    """
    size = ti.get_size()
    for carrier in carriers:
        if carrier.size != size:
            logger.info(
                f"Not retyping {carrier.label}: it holds {carrier.size} bytes, "
                f"{ti.get_type_name()} is {size}."
            )
            continue
        if carrier.retype(vu, ti):
            logger.info(f"Retyped {carrier.label} to {ti.get_type_name()}.")


def apply_enum(
    vu: idaapi.vdui_t,
    ti: idaapi.tinfo_t,
    found: collection_t,
    num: idaapi.cnumber_t | None,
) -> bool:
    """Name the values, then format the number, then retype the class.

    The number goes first because retyping a local re-decompiles the function,
    and the cnumber_t points into the tree that gets thrown away.
    """
    if not name_and_add_members(ti, found.values, found.carriers):
        return False

    if num is not None:
        update_cnumber(num, ti, vu)
    retype_carriers(vu, ti, found.carriers)
    return True


class add_number_to_enum_action_handler_t(base_action_handler_t):
    action_name = "milankovo:add_number_to_enum"
    action_label = "Add to enum"
    action_shortcut = "a"

    def activate(self, ctx: idaapi.action_ctx_base_t):
        vu: idaapi.vdui_t = idaapi.get_widget_vdui(ctx.widget)
        vu.get_current_item(idaapi.USE_KEYBOARD)

        # for switch it returns its cnumber_t that contains the maximum value
        num = current_number(vu)

        found = gather_values(vu)
        if not found.values and not found.carriers:
            return 0
        logger.debug(f"collected {found.describe()}")

        ti = choose_or_create_enum(found.values, found.width)
        if ti is None:
            logger.warning("No enumeration selected. Please try again.")
            return 0

        if not apply_enum(vu, ti, found, num):
            return 0

        global last_enum_used
        last_enum_used = ti.get_type_name()
        return 1

    def update(self, ctx: idaapi.action_ctx_base_t):
        return can_add_to_enum(ctx)


class add_number_to_last_enum_action_handler_t(base_action_handler_t):
    action_name = "milankovo:add_number_to_last_enum"
    action_label = "Add to the last used enum"
    action_shortcut = "shift-a"

    def activate(self, ctx: idaapi.action_ctx_base_t):
        vu: idaapi.vdui_t = idaapi.get_widget_vdui(ctx.widget)
        vu.get_current_item(idaapi.USE_KEYBOARD)

        num = current_number(vu)

        global last_enum_used
        ti = enum_by_name(last_enum_used)
        if ti is None:
            logger.warning("No enumeration selected. Please try again.")
            return 0

        found = gather_values(vu)
        if not found.values and not found.carriers:
            return 0
        logger.debug(f"collected {found.describe()}")

        return 1 if apply_enum(vu, ti, found, num) else 0

    def update(self, ctx: idaapi.action_ctx_base_t):
        global last_enum_used
        if enum_by_name(last_enum_used) is None:
            last_enum_used = None
            return idaapi.AST_DISABLE
        idaapi.update_action_label(self.action_name, f"Add to enum '{last_enum_used}'")
        return can_add_to_enum(ctx)


class rename_enum_member_action_handler_t(base_action_handler_t):
    action_name = "milankovo:rename_enum_member"
    action_label = "Rename enum member"
    action_shortcut = "n"

    def activate(self, ctx: idaapi.action_ctx_base_t):
        vu: idaapi.vdui_t = idaapi.get_widget_vdui(ctx.widget)
        vu.get_current_item(idaapi.USE_KEYBOARD)

        parent = idaapi.tinfo_t()
        idx: int = vu.item.get_edm(parent)
        if idx == -1:
            return 0

        (idx2, edm) = parent.get_edm(idx)

        if idx2 == -1:
            old_name = "???"
        else:
            old_name = edm.name

        new_name = idaapi.ask_str(old_name, idaapi.HIST_IDENT, "New name:")
        if not new_name:
            return 0
        code = parent.rename_edm(idx, new_name, idaapi.ETF_FORCENAME)
        if code != idaapi.TERR_OK:
            logger.error(
                f"Error: cannot rename '{old_name}' to '{new_name}': {idaapi.tinfo_errstr(code)}"
            )
            return 0
        # vu.refresh_ctext(False)
        vu.cfunc.refresh_func_ctext()
        return 1

    def update(self, ctx: idaapi.action_ctx_base_t):
        if ctx.widget_type != idaapi.BWN_PSEUDOCODE:
            return idaapi.AST_DISABLE_FOR_WIDGET

        vu: idaapi.vdui_t = idaapi.get_widget_vdui(ctx.widget)
        vu.get_current_item(idaapi.USE_KEYBOARD)

        parent = idaapi.tinfo_t()
        idx: int = vu.item.get_edm(parent)
        if idx == -1:
            return idaapi.AST_DISABLE
        return idaapi.AST_ENABLE


class EnumsHelperPlugin(idaapi.plugin_t):
    flags = idaapi.PLUGIN_HIDE
    comment = ""
    help = ""
    wanted_name = "enums helper"

    def init(self):
        if not idaapi.init_hexrays_plugin():
            return idaapi.PLUGIN_SKIP

        load_last_enum_used()

        addon = idaapi.addon_info_t()
        addon.id = "milankovo.ida-enums-helper"
        addon.name = "IDA Enums Helper"
        addon.producer = "Milankovo"
        addon.url = "https://github.com/milankovo/ida_enums_helper"
        addon.version = "1.1.0"
        idaapi.register_addon(addon)

        base_action_handler_t.register_actions()

        # Initialize and hook EnumsHelperHooks
        self.hooks = EnumsHelperHooks()
        self.hooks.hook()

        return idaapi.PLUGIN_KEEP

    def term(self):
        base_action_handler_t.unregister_actions()

        # Unhook EnumsHelperHooks
        if hasattr(self, "hooks"):
            self.hooks.unhook()

        save_last_enum_used()

    def run(self, arg):
        pass


class EnumsHelperHooks(idaapi.Hexrays_Hooks):
    def __init__(self):
        super().__init__()

    def populating_popup(self, widget, phandle, vu):
        # Attach actions to the popup menu
        idaapi.attach_action_to_popup(
            vu.ct, None, add_number_to_enum_action_handler_t.action_name
        )
        idaapi.attach_action_to_popup(
            vu.ct, None, add_number_to_last_enum_action_handler_t.action_name
        )
        idaapi.attach_action_to_popup(
            vu.ct, None, rename_enum_member_action_handler_t.action_name
        )
        return 0


def PLUGIN_ENTRY():
    return EnumsHelperPlugin()


def save_last_enum_used():
    logger.debug("Saving last_enum_used")
    global last_enum_used
    if not last_enum_used:
        return

    # The third argument creates the node when it is missing, and setblob
    # overwrites whatever was stored before.
    n = idaapi.netnode(NETNODE_NAME, 0, True)
    n.setblob(last_enum_used.encode(), 0, "I")
    logger.debug(f"Saved last_enum_used: {last_enum_used}")


def load_last_enum_used():
    global last_enum_used
    logger.debug("Loading last_enum_used")
    n = idaapi.netnode(NETNODE_NAME, 0, False)
    v = n.getblob(0, "I")
    if not v:
        logger.debug("netnode load failed or does not exist")
        return

    last_enum_used = v.decode()
    logger.debug(f"Loaded last_enum_used: {last_enum_used}")

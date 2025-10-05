from collections.abc import MutableMapping

#!/usr/bin/python3
from xml.etree import ElementTree as ET


def stringify_value(v):
    if v is None:
        return ""
    return v


class XMLDict(MutableMapping):
    def __init__(self, element):
        self._element = element

    @property
    def text(self):
        return self._element.text

    @text.setter
    def text(self, value):
        self._element.text = stringify_value(value)

    def append(self, tag, attrib=None, text=None):
        child = ET.SubElement(self._element, tag, attrib=attrib or {})
        if text is not None:
            child.text = stringify_value(text)
        return XMLDict(child)

    def __getitem__(self, key):
        if key.startswith("@"):
            attr = key[1:]
            if attr not in self._element.attrib:
                raise KeyError(key)
            return self._element.attrib[attr]

        child = self._element.find(key)
        if child is None:
            raise KeyError(key)

        if list(child) or child.attrib:
            return XMLDict(child)
        return child.text  # leaf node

    def __setitem__(self, key, value):
        if key.startswith("@"):
            self._element.attrib[key[1:]] = stringify_value(value)
            return

        child = self._element.find(key)
        if child is None:
            child = ET.SubElement(self._element, key)

        if isinstance(value, XMLDict):
            self._element.remove(child)
            self._element.append(value._element)

        elif isinstance(value, dict):
            for k, v in value.items():
                if k.startswith("@"):
                    child.attrib[k[1:]] = stringify_value(v)
                elif k == "#text":
                    child.text = stringify_value(v)
                else:
                    # Nested child element
                    sub = child.find(k)
                    if sub is None:
                        sub = ET.SubElement(child, k)
                    sub.text = stringify_value(v)
        else:
            child.text = stringify_value(value)

    def __delitem__(self, key):
        if key.startswith("@"):
            attr = key[1:]
            if attr not in self._element.attrib:
                raise KeyError(key)
            del self._element.attrib[attr]
            return

        child = self._element.find(key)
        if child is None:
            raise KeyError(key)
        self._element.remove(child)

    def __iter__(self):
        for attr in self._element.attrib:
            yield "@" + attr
        for child in self._element:
            yield child.tag

    def __len__(self):
        return len(self._element.attrib) + len(self._element)

    def __repr__(self):
        return f"<XMLDict {self._element.tag}: {dict(self.items())}> {self.text}"


class ConfigXML(XMLDict):
    def __init__(self, filename):
        self._filename = filename
        self._tree = ET.parse(filename)
        super().__init__(self._tree.getroot())

    def save(self, filename=None):
        self._tree.write(filename or self._filename, encoding="utf-8", short_empty_elements=False)


def inspect_xml(root):
    from rich.console import Console
    from rich.tree import Tree

    def rich_walk(elem, tree=None):
        branch = Tree(f"[bold]{elem.tag}[/] {elem.attrib or elem.text}")
        for child in elem:
            branch.add(rich_walk(child))
        return branch

    console = Console()
    console.print(rich_walk(root))


if __name__ == "__main__":
    config = ConfigXML("config.xml")
    config["options"]["urAccepted"] = "-1"

    device = config["device"]
    print("Device id:", device["@id"])
    device["@id"] = "NEW-DEVICE-ID"

    gui = config["gui"]
    print("GUI address:", gui["address"])
    gui["address"] = "127.0.0.1:9999"
    minDiskFree = config["options"].append("minDiskFree")
    minDiskFree["@unit"] = "%"
    minDiskFree.text = "1"
    print(config["options"]["minDiskFree"])

    config.save("config_modified.xml")

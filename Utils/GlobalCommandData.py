from discord import app_commands

# Global Descriptions
globalColorDescription = "Enter a hex code. (e.g., FF00FF or #334CB2)"
globalPieceTypeDescription = "Enter the armor piece type. (e.g., helmet, chest, etc...)"
globalColorListDescription = "Enter a list of hex codes separated by spaces (e.g., #334CB2 #191919)"
globalOutputShapeDescription = "Enter the armor shape. (e.g., Vertical, Horizontal, Square)"
GlobalOutputVersionDescription = "Enter the armor version. (e.g., 1.8.9, 1.14+)"

# Global Choices
globalShapeChoices = [
    app_commands.Choice(name="Vertical", value="Vertical"),
    app_commands.Choice(name="Horizontal", value="Horizontal"),
    app_commands.Choice(name="Square", value="Square"),
]
globalNormalShapeChoices = [
    app_commands.Choice(name="Vertical", value="Vertical"),
    app_commands.Choice(name="Horizontal", value="Horizontal"),
]
globalArmorVersionChoices = [
    app_commands.Choice(name="1.8.9", value="1.8.9"),
    app_commands.Choice(name="1.14+", value="1.14+")
]
globalPieceTypeChoices = [
    app_commands.Choice(name="Helmet", value="Helmet"),
    app_commands.Choice(name="Chestplate", value="Chestplate"),
    app_commands.Choice(name="Leggings", value="Leggings"),
    app_commands.Choice(name="Boots", value="Boots"),
]

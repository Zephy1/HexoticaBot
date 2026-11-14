from discord import app_commands

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

from discord.ext import commands
from json_file import File
from slash import SlashCommand, slash_command, slash_option, slash_cooldown
import discord
import os
import yaml
# Todo: on_role_name_update, on_category_name_update, on_faction_name_update


MESSAGE = discord.InteractionResponseType.channel_message
MESSAGE_WITH_SOURCE = discord.InteractionResponseType.channel_message_with_source


class Bot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix='/',
            owner_ids=[376100578683650048, 404360461065256965]
        )
        self.factions = File('factions.json')
        self.slash_commands = {}

    async def on_ready(self):
        await self.register_commands()
        print('Eingeloggt als', self.user.name)

    async def process_interaction(self, interaction):
        try:
            command = self.slash_commands[interaction.command_id]
        except KeyError:
            return
        retry_after = command.update_rate_limit(interaction)
        if retry_after:
            return await self.on_command_cooldown(interaction, retry_after)
        options = {option.name: option.value for option in interaction.options}
        await command.callback(self, interaction, **options)

    def reset_cooldown(self, interaction):
        command = self.slash_commands[interaction.command_id]
        if command._buckets.valid:
            key = command._buckets._bucket_key(interaction)
            command._buckets._cache[key]._tokens = command._buckets._cooldown.rate

    async def register_commands(self):
        guild_id = 784103863258841090
        for name in dir(self):
            attr = getattr(self, name)
            if isinstance(attr, SlashCommand):
                data = await self.http.create_guild_application_command(guild_id, attr.to_dict())
                self.slash_commands[int(data['id'])] = attr

    async def on_command_cooldown(self, interaction, retry_after):
        mins, secs = divmod(int(retry_after), 60)
        hours, mins = divmod(mins, 60)
        if hours:
            text = f'{hours}h{mins}m{secs}s'
        elif mins:
            text = f'{mins}m{secs}s'
        else:
            text = str(round(retry_after, 1)) + 's'
        await interaction.send(f'Bitte warte noch `{text}`, bevor du diesen Command wieder benutzen kannst.', type=MESSAGE, flags=64)

    def get_faction(self, member):
        roles = [role.id for role in member.roles]
        for faction in self.factions:
            if faction['role_id'] in roles:
                return faction

    @slash_command(name='ipcheck', description='Checkt, ob es Nutzer auf dem Minecraftserver gibt, die die selbe IP-Adresse haben.')
    @slash_cooldown(1, 2*60, commands.BucketType.user)
    async def ipcheck(self, ctx):
        if not ctx.author.top_role.permissions.administrator:
            return await ctx.send('Du hast keine Berechtigung, um diesen Command auszuführen.', type=MESSAGE, flags=64)
        base = '/home/inspektor/ftp/minecraft/plugins/Essentials/userdata/'
        mapping = {}
        for filename in os.listdir(base):
            with open(base + filename) as file:
                data = yaml.load(file, Loader=yaml.FullLoader)
            ip = data['ipAddress']
            name = data['lastAccountName']
            if ip in mapping:
                mapping[ip].append(name)
            else:
                mapping[ip] = [name]
        msg = '\n'.join(f'`{ip}`: {", ".join(names)}' for ip, names in mapping.items() if len(names) > 1)
        if not msg:
            msg = 'Keine Duplikate gefunden.'
        await ctx.send(msg, type=MESSAGE, flags=64)

    @slash_command(name='create', description='Erstellt eine Fraktion mit dem gewünschten Namen.')
    @slash_option(name='name', description='Bitte gib einen Namen fuer deine Fraktion ein.', type=3, required=True)
    @slash_cooldown(1, 12*60*60, commands.BucketType.user)
    async def create(self, ctx, name):
        faction = self.get_faction(ctx.author)
        if faction is not None:
            self.reset_cooldown(ctx)
            return await ctx.send(f'Du bist bereits in einer Fraktion! (**{faction["name"]}**)', type=MESSAGE, flags=64)
        taken = False
        for faction in self.factions:
            if faction['name'].casefold() == name.casefold():
                taken = True
                break
        if taken:
            self.reset_cooldown(ctx)
            return await ctx.send('Eine andere Fraktion mit diesem Namen existiert bereits.', type=MESSAGE, flags=64)
        role = await ctx.guild.create_role(name=name, hoist=True, mentionable=True)
        self.loop.create_task(ctx.author.add_roles(role))
        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(send_messages=False, connect=False),
            role: discord.PermissionOverwrite(send_messages=True, connect=True)
        }
        category = await ctx.guild.create_category(f'⊱──┤ {name} ├──⊰', overwrites=overwrites)
        await category.create_voice_channel('└Talk🔊', overwrites=overwrites)
        chat = await category.create_text_channel('┌chat💬', overwrites=overwrites)
        overwrites[ctx.guild.default_role].view_channel = False
        overwrites[role].view_channel = True
        await category.create_text_channel('├privat🔒', overwrites=overwrites)
        self.factions.append({
            'name': name,
            'category_id': category.id,
            'role_id': role.id,
            'owner_id': ctx.author.id,
            'public': False,
            'invites': [],
            'bans': []
        })
        await self.factions.save()
        await ctx.send(f'Deine Fraktion wurde erstellt. ({chat.mention})', type=MESSAGE_WITH_SOURCE)

    @slash_command(name='delete', description='Loescht deine Fraktion. Das kann nicht rueckgaengig gemacht werden.')
    async def delete(self, ctx):
        faction = self.get_faction(ctx.author)
        if faction is None:
            return await ctx.send(f'Du bist in keiner Fraktion!', type=MESSAGE, flags=64)
        if ctx.author.id != faction['owner_id']:
            return await ctx.send('Du bist nicht der Besitzer deiner Fraktion.', type=MESSAGE, flags=64)
        category = ctx.guild.get_channel(faction['category_id'])
        for channel in category.channels:
            await channel.delete()
        await category.delete()
        role = ctx.guild.get_role(faction['role_id'])
        await role.delete()
        self.factions.remove(faction)
        await self.factions.save()
        await ctx.send('Deine Fraktion wurde gelöscht.', type=MESSAGE_WITH_SOURCE)

    @slash_command(name='leave', description='Verlaesst deine Fraktion.')
    async def leave(self, ctx):
        faction = self.get_faction(ctx.author)
        if faction is None:
            return await ctx.send(f'Du bist in keiner Fraktion!', type=MESSAGE, flags=64)
        if ctx.author.id == faction['owner_id']:
            return await ctx.send('Du kannst deine Fraktion nicht verlassen, da du der Besitzer bist.', type=MESSAGE, flags=64)
        role = ctx.guild.get_role(faction['role_id'])
        await ctx.author.remove_roles(role)
        await ctx.send('Du hast deine Fraktion verlassen.', type=MESSAGE_WITH_SOURCE)

    @slash_command(name='join', description='Tritt einer Fraktion mit dem gewünschten Namen bei.')
    @slash_option(name='name', description='Bitte gib einen Namen fuer eine Fraktion ein.', type=3, required=True)
    @slash_cooldown(1, 12*60*60, commands.BucketType.user)
    async def join(self, ctx, name):
        faction = self.get_faction(ctx.author)
        if faction is not None:
            self.reset_cooldown(ctx)
            return await ctx.send(f'Du bist bereits in einer Fraktion! ({faction["name"]})', type=MESSAGE, flags=64)
        found = None
        for faction in self.factions:
            if faction['name'].casefold() == name.casefold():
                found = faction
                break
        if not found:
            self.reset_cooldown(ctx)
            return await ctx.send('Diese Fraktion existiert nicht. Bitte stelle sicher, dass du den Namen richtig geschrieben hast.', type=MESSAGE, flags=64)
        if ctx.author.id in faction['bans']:
            self.reset_cooldown(ctx)
            return await ctx.send('Du wurdest von dieser Fraktion gebannt.', type=MESSAGE, flags=64)
        if not faction['public']:
            if ctx.author.id in faction['invites']:
                self.factions[self.factions.index(faction)]['invites'].remove(ctx.author.id)
                await self.factions.save()
            else:
                self.reset_cooldown(ctx)
                return await ctx.send('Diese Fraktion ist auf privat gestellt.', type=MESSAGE, flags=64)
        await ctx.author.add_roles(discord.Object(id=faction['role_id']))
        await ctx.send(f'Du bist **{faction["name"]}** beigetreten!', type=MESSAGE_WITH_SOURCE)

    @slash_command(name='rename', description='Benennt deine Fraktion um.')
    @slash_option(name='name', description='Bitte gib einen neuen Namen fuer dedine Fraktion ein.', type=3, required=True)
    @slash_cooldown(2, 10*60, commands.BucketType.user)
    async def rename(self, ctx, name):
        faction = self.get_faction(ctx.author)
        if faction is None:
            self.reset_cooldown(ctx)
            return await ctx.send('Du bist in keiner Fraktion!', type=MESSAGE, flags=64)
        if ctx.author.id != faction['owner_id']:
            self.reset_cooldown(ctx)
            return await ctx.send('Du bist nicht der Besitzer deiner Fraktion.', type=MESSAGE, flags=64)
        taken = False
        for faction in self.factions:
            if faction['name'].casefold() == name.casefold():
                taken = True
                break
        if taken:
            self.reset_cooldown(ctx)
            return await ctx.send('Eine andere Fraktion mit diesem Namen existiert bereits.', type=MESSAGE, flags=64)
        self.factions[self.factions.index(faction)]['name'] = name
        category = ctx.guild.get_channel(faction['category_id'])
        await category.edit(name=name)
        role = ctx.guild.get_role(faction['role_id'])
        await role.edit(name=name)
        await self.factions.save()
        await ctx.send('Der Name deiner Fraktion wurde geaendert.', type=MESSAGE_WITH_SOURCE)

    @slash_command(name='public', description='Stellt um, ob deine Fraktion oeffentlich ist.')
    @slash_option(name='value', description='Soll deine Fraktion oeffentlich gemacht werden?', type=5)
    async def public(self, ctx, value=None):
        faction = self.get_faction(ctx.author)
        if faction is None:
            return await ctx.send('Du bist in keiner Fraktion!', type=MESSAGE, flags=64)
        if ctx.author.id != faction['owner_id']:
            return await ctx.send('Du bist nicht der Besitzer deiner Fraktion.', type=MESSAGE, flags=64)
        if value is None:
            value = not faction['public']
        if value == faction['public']:
            return await ctx.send('Es wurden keine Aenderrungen vorgenommen.', type=MESSAGE, flags=64)
        self.factions[self.factions.index(faction)]['public'] = value
        await self.factions.save()
        text = 'oeffentlich' if value else 'privat'
        await ctx.send(f'Deine Fraktion wurde auf {text} gesetzt.', type=MESSAGE_WITH_SOURCE)

    @slash_command(name='color', description='Aendert die Farbe der Rolle deiner Fraktion.')
    @slash_option(name='color', description='Bitte gib eine Farbe an? (Hex)', type=3, required=True)
    @slash_cooldown(2, 600, commands.BucketType.user)
    async def color(self, ctx, color):
        faction = self.get_faction(ctx.author)
        if faction is None:
            self.reset_cooldown(ctx)
            return await ctx.send('Du bist in keiner Fraktion!', type=MESSAGE, flags=64)
        if ctx.author.id != faction['owner_id']:
            self.reset_cooldown(ctx)
            return await ctx.send('Du bist nicht der Besitzer deiner Fraktion.', type=MESSAGE, flags=64)
        try:
            color = await commands.ColorConverter().convert(ctx, color)
        except commands.BadColourArgument:
            self.reset_cooldown(ctx)
            return await ctx.send('Die angegebene Farbe ist ungueltig.', type=MESSAGE, flags=64)
        role = ctx.guild.get_role(faction['role_id'])
        await role.edit(color=color)
        await ctx.send('Die Farbe der Fraktionsrolle wurde geaendert.', type=MESSAGE_WITH_SOURCE)

    @slash_command(name='invite', description='Laedt ein Mitglied in deine Fraktion ein.')
    @slash_option(name='user', description='Gib ein Mitglied an, welches du einladen moechtest.', type=6, required=True)
    async def invite(self, ctx, user):
        faction = self.get_faction(ctx.author)
        if faction is None:
            return await ctx.send('Du bist in keiner Fraktion!', type=MESSAGE, flags=64)
        if ctx.author.id != faction['owner_id']:
            return await ctx.send('Du bist nicht der Besitzer deiner Fraktion.', type=MESSAGE, flags=64)
        member = await ctx.guild.fetch_member(int(user))
        if member.bot:
            return await ctx.send('Du kannst keine Bots einladen.', type=MESSAGE, flags=64)
        if member == ctx.author:
            return await ctx.send('Du kannst dich nicht selbst einladen.', type=MESSAGE, flags=64)
        for role in member.roles:
            if role.id == faction['role_id']:
                return await ctx.send('Dieses Mitglied ist bereits in deiner Fraktion.', type=MESSAGE, flags=64)
        self.factions[self.factions.index(faction)]['invites'].append(member.id)
        await self.factions.save()
        await ctx.send(f'Du hast {member.mention} eingeladen, deiner Fraktion beizutreten.', type=MESSAGE_WITH_SOURCE)

    @slash_command(name='kick', description='Entfernt ein Mitglied aus deiner Fraktion.')
    @slash_option(name='user', description='Gib ein Mitglied an, welches du kicken moechtest.', type=6, required=True)
    async def kick(self, ctx, user):
        faction = self.get_faction(ctx.author)
        if faction is None:
            return await ctx.send('Du bist in keiner Fraktion!', type=MESSAGE, flags=64)
        if ctx.author.id != faction['owner_id']:
            return await ctx.send('Du bist nicht der Besitzer deiner Fraktion.', type=MESSAGE, flags=64)
        member = await ctx.guild.fetch_member(int(user))
        if member.bot:
            return await ctx.send('Du kannst keine Bots kicken.', type=MESSAGE, flags=64)
        if member == ctx.author:
            return await ctx.send('Du kannst dich nicht selbst kicken.', type=MESSAGE, flags=64)
        found = False
        for role in member.roles:
            if role.id == faction['role_id']:
                found = True
        if not found:
            return await ctx.send('Diese Person ist nicht in deiner Fraktion', type=MESSAGE, flags=64)
        await member.remove_roles(discord.Object(id=faction['role_id']))
        await ctx.send(f'Du hast {member.mention} aus deiner Fraktion entfernt.', type=MESSAGE_WITH_SOURCE)

    @slash_command(name='ban', description='Verbannt ein Mitglied aus deiner Fraktion.')
    @slash_option(name='user', description='Gib ein Mitglied an, welches du bannen moechtest.', type=6, required=True)
    async def ban(self, ctx, user):
        faction = self.get_faction(ctx.author)
        if faction is None:
            return await ctx.send('Du bist in keiner Fraktion!', type=MESSAGE, flags=64)
        if ctx.author.id != faction['owner_id']:
            return await ctx.send('Du bist nicht der Besitzer deiner Fraktion.', type=MESSAGE, flags=64)
        member = await ctx.guild.fetch_member(int(user))
        if member.bot:
            return await ctx.send('Du kannst keine Bots bannen.', type=MESSAGE, flags=64)
        if member == ctx.author:
            return await ctx.send('Du kannst dich nicht selbst bannen.', type=MESSAGE, flags=64)
        found = False
        for role in member.roles:
            if role.id == faction['role_id']:
                found = True
        if found:
            await member.remove_roles(discord.Object(id=faction['role_id']))
        if member.id in faction['invites']:
            self.factions[self.factions.index(faction)]['invites'].remove(member.id)
        self.factions[self.factions.index(faction)]['bans'].append(member.id)
        await self.factions.save()
        await ctx.send(f'Du hast {member.mention} aus deiner Fraktion verbannt.', type=MESSAGE_WITH_SOURCE)

    @slash_command(name='unban', description='Entbannt ein Mitglied aus deiner Fraktion.')
    @slash_option(name='user', description='Gib ein Mitglied an, welches du entbannen moechtest.', type=6, required=True)
    async def unban(self, ctx, user):
        faction = self.get_faction(ctx.author)
        if faction is None:
            return await ctx.send('Du bist in keiner Fraktion!', type=MESSAGE, flags=64)
        if ctx.author.id != faction['owner_id']:
            return await ctx.send('Du bist nicht der Besitzer deiner Fraktion.', type=MESSAGE, flags=64)
        member = await ctx.guild.fetch_member(int(user))
        if member.bot:
            return await ctx.send('Du kannst keine Bots entbannen.', type=MESSAGE, flags=64)
        if member == ctx.author:
            return await ctx.send('Du kannst dich nicht selbst entbannen.', type=MESSAGE, flags=64)
        try:
            self.factions[self.factions.index(faction)]['bans'].remove(member.id)
        except ValueError:
            await ctx.send('Diese Person ist nicht gebannt.', type=MESSAGE, flags=64)
        else:
            await self.factions.save()
            await ctx.send(f'Du hast {member.mention} aus deiner Fraktion entbannt.', type=MESSAGE_WITH_SOURCE)

    @slash_command(name='promote', description='Uebergibt die Besitzrechte deiner Fraktion.')
    @slash_option(name='user', description='Gib ein Mitglied an, welchem du die Besitzrechte uebergeben moechtest.', type=6, required=True)
    async def promote(self, ctx, user):
        faction = self.get_faction(ctx.author)
        if faction is None:
            return await ctx.send('Du bist in keiner Fraktion!', type=MESSAGE, flags=64)
        if ctx.author.id != faction['owner_id']:
            return await ctx.send('Du bist nicht der Besitzer deiner Fraktion.', type=MESSAGE, flags=64)
        member = await ctx.guild.fetch_member(int(user))
        if member.bot:
            return await ctx.send('Du kannst keinen Bots Besitzrechte uebergeben.', type=MESSAGE, flags=64)
        if member == ctx.author:
            return await ctx.send('Du bist bereits der Besitzer deiner Fraktion.', type=MESSAGE, flags=64)
        found = False
        for role in member.roles:
            if role.id == faction['role_id']:
                found = True
        if not found:
            return await ctx.send('Diese Person ist nicht in deiner Fraktion', type=MESSAGE, flags=64)
        self.factions[self.factions.index(faction)]['owner_id'] = member.id
        await self.factions.save()
        await ctx.send(f'Du hast {member.mention} die Besitzrechte deiner Fraktion uebergeben.', type=MESSAGE_WITH_SOURCE)

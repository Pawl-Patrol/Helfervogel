import discord
from discord.ext import commands
import datetime


class SlashCommand:
    def __init__(self, func, *, name, description):
        self.callback = func
        self.name = name
        self.description = description
        self.options = []
        self._buckets = commands.CooldownMapping(None)

    def update_rate_limit(self, ctx):
        if self._buckets.valid:
            current = datetime.datetime.utcnow().timestamp()
            return self._buckets.update_rate_limit(ctx, current)

    def to_dict(self):
        return {
            'name': self.name,
            'description': self.description,
            'options': [opt.to_dict() for opt in self.options]
        }


def slash_command(*, name, description, cls=SlashCommand):
    def decorator(func):
        if isinstance(func, SlashCommand):
            raise TypeError('Callback is already an application-command.')
        command = cls(func, name=name, description=description)
        if hasattr(func, '__application_command_options__'):
            command.options = func.__application_command_options__
        if hasattr(func, '__commands_cooldown__'):
            command._buckets = commands.CooldownMapping(func.__commands_cooldown__)
        return command
    return decorator


def slash_option(**kwargs):
    def decorator(func):
        option = discord.ApplicationCommandOption(**kwargs)
        if isinstance(func, SlashCommand):
            func.options.append(option)
        else:
            if hasattr(func, '__application_command_options__'):
                func.__application_command_options__.append(option)
            else:
                func.__application_command_options__ = [option]
        return func

    return decorator


def slash_cooldown(rate, per, type):
    def decorator(func):
        if isinstance(func, SlashCommand):
            func._buckets = commands.CooldownMapping.from_cooldown(rate, per, type)
        else:
            func.__commands_cooldown__ = commands.Cooldown(rate, per, type)
        return func
    return decorator

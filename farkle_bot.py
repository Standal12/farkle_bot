import discord
from discord.ext import commands
import random
from collections import Counter
import os

# TODO: Show scores
# ----- Bot Setup -----
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ----- Game State -----
games = {}

# ----- Dice Emojis (one-sided) -----
DICE_EMOJIS = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}


# ----- Scoring -----
def is_scoring_dice(dice):
    counts = Counter(dice)
    if len(dice) == 6:
        twos = 0
        threes = 0
        fours = 0
        straight = 0
        for num, count in counts.items():
            if count == 4:
                fours += 1
            if count == 3:
                threes += 1
            if count == 2:
                twos += 1
            if count == 1:
                straight += 1
        if threes == 2:
            return (True, 2500)
        if fours == 1 and twos == 1:
            return (True, 1500)
        if twos == 3:
            return (True, 1500)
        if straight == 6:
            return (True, 1500)
    score = 0
    bool = True
    for num, count in counts.items():
        if count >= 3:
            if num == 1:
                score += 2**(count - 3) * 1000
            else:
                score += 2**(count - 3) * 100 * num
            count = 0
        if num == 1 or num == 5:
            score += count * (100 if num == 1 else 50)
            count = 0
        if count > 0:
            bool = False
    return (bool, score)


# ----- Game Class -----
class FarkleGame:

    def __init__(self, starter, winning_score=10000):
        self.players = []
        self.scores = {}
        self.current_turn = 0
        self.turn_score = 0
        self.remaining_dice = 6
        self.current_roll = []
        self.kept_this_roll = False
        self.started = False
        self.starter = starter
        self.winning_score = winning_score

    @property
    def current_player(self):
        return self.players[self.current_turn]

    def next_turn(self):
        self.turn_score = 0
        self.remaining_dice = 6
        self.current_roll = []
        self.kept_this_roll = False
        if len(self.players) > 1:
            self.current_turn = (self.current_turn + 1) % len(self.players)


# ----- View -----
class FarkleView(discord.ui.View):

    def __init__(self, game):
        super().__init__(timeout=None)
        self.game = game
        self.selected_indices = set()

    def dice_buttons(self):
        self.clear_items()
        n = len(self.game.current_roll)

        # Dice layout
        if n == 6:
            for i, die in enumerate(self.game.current_roll):
                row = 0 if i < 3 else 1
                self.add_item(DiceButton(i, die, self, row=row))
        else:
            for i, die in enumerate(self.game.current_roll):
                self.add_item(DiceButton(i, die, self, row=0))

        # Roll / Keep / Bank buttons below dice
        self.add_item(RollButton(self, row=2))
        self.add_item(KeepButton(self, row=2))
        self.add_item(BankButton(self, row=2))
        return self


# ----- Buttons -----
class DiceButton(discord.ui.Button):

    def __init__(self, index, value, view_ref, row=0):
        super().__init__(label=DICE_EMOJIS[value],
                         style=discord.ButtonStyle.secondary,
                         row=row)
        self.index = index
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        game = self.view_ref.game
        if interaction.user != game.current_player:
            return await interaction.response.send_message(
                "It's not your turn!", ephemeral=True)

        # Toggle selection
        if self.index in self.view_ref.selected_indices:
            self.view_ref.selected_indices.remove(self.index)
        else:
            self.view_ref.selected_indices.add(self.index)

        # Update button styles to highlight selected dice
        for item in self.view_ref.children:
            if isinstance(item, DiceButton):
                if item.index in self.view_ref.selected_indices:
                    item.style = discord.ButtonStyle.success
                else:
                    item.style = discord.ButtonStyle.secondary

        await interaction.response.edit_message(view=self.view_ref)


class RollButton(discord.ui.Button):

    def __init__(self, view_ref, row=2):
        super().__init__(label="Roll",
                         style=discord.ButtonStyle.primary,
                         row=row)
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        game = self.view_ref.game
        if interaction.user != game.current_player:
            return await interaction.response.send_message(
                "It's not your turn!", ephemeral=True)

        if game.current_roll and not game.kept_this_roll:
            return await interaction.response.send_message(
                "You must keep at least some dice from your previous roll before rolling again!",
                ephemeral=True)

        game.current_roll = [
            random.randint(1, 6) for _ in range(game.remaining_dice)
        ]
        game.kept_this_roll = False
        self.view_ref.selected_indices = set()

        # Check Farkle
        legal, score = is_scoring_dice(game.current_roll)
        if score == 0:
            game.turn_score = 0
            game.next_turn()
            await interaction.response.edit_message(
                content=
                f"💥 **Farkle!** No points this turn.\n➡️ Next turn: {game.current_player.display_name}",
                view=self.view_ref.dice_buttons())
            return

        await interaction.response.edit_message(
            content=
            f"🎲 Rolled {len(game.current_roll)} dice. Select dice to keep.",
            view=self.view_ref.dice_buttons())


class KeepButton(discord.ui.Button):

    def __init__(self, view_ref, row=2):
        super().__init__(label="Keep",
                         style=discord.ButtonStyle.success,
                         row=row)
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        game = self.view_ref.game
        if interaction.user != game.current_player:
            return await interaction.response.send_message(
                "It's not your turn!", ephemeral=True)

        if not self.view_ref.selected_indices:
            return await interaction.response.send_message(
                "Select at least one die to keep!", ephemeral=True)

        kept_dice = [
            game.current_roll[i] for i in self.view_ref.selected_indices
        ]
        legal, score = is_scoring_dice(kept_dice)
        if not legal:
            return await interaction.response.send_message(
                "Not all selected dice score points!", ephemeral=True)

        game.turn_score += score
        game.remaining_dice -= len(kept_dice)
        game.kept_this_roll = True
        game.current_roll = [
            game.current_roll[i] for i in range(len(game.current_roll))
            if i not in self.view_ref.selected_indices
        ]
        self.view_ref.selected_indices = set()

        if game.remaining_dice == 0:
            game.remaining_dice = 6

        await interaction.response.edit_message(
            content=
            f"Kept dice score: {score}\nTurn score: {game.turn_score}\nRemaining dice: {game.remaining_dice}",
            view=self.view_ref.dice_buttons())


class BankButton(discord.ui.Button):

    def __init__(self, view_ref, row=2):
        super().__init__(label="Bank",
                         style=discord.ButtonStyle.secondary,
                         row=row)
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        game = self.view_ref.game
        if interaction.user != game.current_player:
            return await interaction.response.send_message(
                "It's not your turn!", ephemeral=True)

        if not game.kept_this_roll:
            return await interaction.response.send_message(
                "You must keep some scoring dice from this roll before banking!",
                ephemeral=True)

        game.scores[interaction.user] += game.turn_score
        total = game.scores[interaction.user]
        winner = None
        if total >= game.winning_score:
            winner = interaction.user
            del games[interaction.channel.id]
        else:
            game.next_turn()

        self.view_ref.selected_indices = set()

        if winner:
            await interaction.response.edit_message(
                content=
                f"🏆 {winner.display_name} reached {total} points and wins the game! 🎉",
                view=None)
        else:
            await interaction.response.edit_message(
                content=
                f"💾 {interaction.user.display_name} banked points: {total}\n➡️ Next turn: {game.current_player.display_name}",
                view=self.view_ref.dice_buttons())


# ----- Commands -----
@bot.command()
async def farkle(ctx):
    if ctx.channel.id in games:
        return await ctx.send("A Farkle game is already running!")
    game = FarkleGame(starter=ctx.author)
    game.players.append(ctx.author)
    game.scores[ctx.author] = 0
    games[ctx.channel.id] = game
    await ctx.send(
        "🎲 **Farkle Game Created!**\n"
        "You can join with `!join` or start with `!start <winning_score>` (default 10,000)"
    )


@bot.command()
async def join(ctx):
    game = games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No Farkle game is running.")
    if ctx.author in game.players:
        return await ctx.send("You already joined!")
    game.players.append(ctx.author)
    game.scores[ctx.author] = 0
    await ctx.send(f"{ctx.author.display_name} joined the game!")


@bot.command()
async def start(ctx, winning_score: int = 10000):
    game = games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No Farkle game is running.")
    game.winning_score = winning_score
    if len(game.players) == 0:
        game.players.append(ctx.author)
        game.scores[ctx.author] = 0
    game.started = True
    view = FarkleView(game)
    await ctx.send(
        f"🎲 **Game Started! Winning score: {game.winning_score}**\n➡️ First turn: **{game.current_player.display_name}**",
        view=view.dice_buttons())


@bot.command()
async def stop(ctx):
    game = games.get(ctx.channel.id)
    if not game:
        return await ctx.send("No Farkle game is running.")
    if ctx.author != game.starter:
        return await ctx.send(
            "Only the player who started the game can stop it!")
    del games[ctx.channel.id]
    await ctx.send("🛑 The Farkle game has been stopped.")


# ----- Run Bot -----
bot.run(os.getenv("DISCORD_TOKEN"))

import pygame
import sys

SCREEN_W = 800
SCREEN_H = 600
FPS = 60
TILE_SIZE = 48


#colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
DARK_GREY = (40,40,40) # floor color
STONE = (100,100,100) # wall color

# Tile types
FLOOR = 0
WALL = 1





MAP =[
    [1,1,1,1,1,1,1,1,1],
    [1,0,0,0,0,0,0,0,1],
    [1,0,0,0,0,0,0,0,1],
    [1,0,0,0,0,0,0,0,1],
    [1,0,0,0,0,0,0,0,1],
    [1,0,0,0,0,0,0,0,1],
    [1,1,1,1,1,1,1,1,1],

]

# player class
class Player:
    def __init__(self, x, y):
        self.rect = pygame.Rect(x, y, TILE_SIZE - 4, TILE_SIZE - 4)
        self.color = (255, 200, 0)
        self.speed = 3

    def draw(self, surface):
        pygame.draw.rect(surface, self.color, self.rect)

    def update(self):
        keys = pygame.key.get_pressed()

        if keys[pygame.K_w] or keys[pygame.K_UP]:
            self.rect.y -= self.speed
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            self.rect.y += self.speed
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            self.rect.x -= self.speed
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            self.rect.x += self.speed

def get_tile(x, y):
    col = x // TILE_SIZE
    row = y // TILE_SIZE
    if row < 0 or row >= len(MAP):
        return WALL
    if col < 0 or col >= len(MAP[row]):
        return WALL
    return MAP[row][col]

# Draw the map
def draw_map(surface):
    for row_idx, row in enumerate(MAP):
        for col_idx, tile in enumerate(row):
            # pixel position = index * title size
            x = col_idx * TILE_SIZE
            y = row_idx * TILE_SIZE
            if tile == WALL:
                color = STONE
            else: color = DARK_GREY

            # draw the rectangle

            pygame.draw.rect(surface, color, (x, y, TILE_SIZE, TILE_SIZE))

            # draw a thin border so we can see the grid
            pygame.draw.rect(surface, BLACK, (x, y, TILE_SIZE, TILE_SIZE),1)
# ---INIT---
pygame.init()
screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
pygame.display.set_caption("Walkable Room")
clock = pygame.time.Clock()

player = Player(48,48)

while True:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()

    screen.fill(BLACK)
    player.update()
    draw_map(screen)
    player.draw(screen)

    pygame.display.flip()
    clock.tick(FPS)